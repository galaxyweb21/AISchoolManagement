# school/scheduler_engine.py
import random
from typing import List, Dict, Tuple, Set, Optional
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ClassGene:
    """
    Represents a single scheduled class instance (a Gene).
    """
    cohort_id: str  # e.g., "Grade-10A"
    subject_id: str  # e.g., "AP-CHEM"
    teacher_id: str  # e.g., "Teacher-Marcus"
    room_id: str  # e.g., "Room-302"
    timeslot_id: str  # e.g., "MON-0900" (Unique identifier for day + hour block)
    room_capacity: int  # Capacity limit of the room
    student_count: int  # Active number of students enrolled in this cohort
    is_lab_required: bool
    is_room_lab: bool


class ScheduleChromosome:
    """
    Represents a complete, candidate school timetable (a Chromosome).
    """

    def __init__(self, genes: List[ClassGene]):
        self.genes = genes
        self.fitness: float = 0.0
        self.hard_conflicts: int = 0
        self.soft_conflicts: int = 0
        self.conflicting_gene_indices: Set[int] = set()


class TimetableEvaluator:
    """
    The main fitness evaluator that parses timetables and scores them.
    """
    # Penalty weights
    HARD_CONSTRAINT_PENALTY = 100
    SOFT_CONSTRAINT_PENALTY = 10

    @classmethod
    def calculate_fitness(cls, chromosome: ScheduleChromosome) -> float:
        """Evaluate hard constraints first, then timetable quality preferences."""
        hard_conflicts = 0
        soft_conflicts = 0
        conflicting_indices: Set[int] = set()

        teacher_claims: Dict[Tuple[str, str], int] = {}
        room_claims: Dict[Tuple[str, str], int] = {}
        cohort_claims: Dict[Tuple[str, str], int] = {}
        teacher_daily_blocks: Dict[Tuple[str, str], List[int]] = {}
        cohort_daily_slots: Dict[Tuple[str, str], List[int]] = {}
        cohort_subject_days: Dict[Tuple[str, str], Set[str]] = {}
        cohort_subject_slots: Dict[Tuple[str, str], List[Tuple[str, int]]] = {}
        cohort_day_load: Dict[Tuple[str, str], int] = {}

        for idx, gene in enumerate(chromosome.genes):
            t_slot = gene.timeslot_id
            day_prefix, slot_value = cls._slot_parts(t_slot)

            # ---------------------------
            # Hard constraints
            # ---------------------------
            teacher_key = (gene.teacher_id, t_slot)
            if teacher_key in teacher_claims:
                hard_conflicts += 1
                conflicting_indices.update((idx, teacher_claims[teacher_key]))
            else:
                teacher_claims[teacher_key] = idx

            room_key = (gene.room_id, t_slot)
            if room_key in room_claims:
                hard_conflicts += 1
                conflicting_indices.update((idx, room_claims[room_key]))
            else:
                room_claims[room_key] = idx

            cohort_key = (gene.cohort_id, t_slot)
            if cohort_key in cohort_claims:
                hard_conflicts += 1
                conflicting_indices.update((idx, cohort_claims[cohort_key]))
            else:
                cohort_claims[cohort_key] = idx

            if gene.student_count > gene.room_capacity:
                hard_conflicts += 1
                conflicting_indices.add(idx)

            if gene.is_lab_required and not gene.is_room_lab:
                hard_conflicts += 1
                conflicting_indices.add(idx)

            # ---------------------------
            # Soft-quality tracking
            # ---------------------------
            if slot_value is not None:
                teacher_daily_blocks.setdefault((gene.teacher_id, day_prefix), []).append(slot_value)
                cohort_daily_slots.setdefault((gene.cohort_id, day_prefix), []).append(slot_value)
                cohort_day_load[(gene.cohort_id, day_prefix)] = cohort_day_load.get((gene.cohort_id, day_prefix), 0) + 1
                key = (gene.cohort_id, gene.subject_id)
                cohort_subject_days.setdefault(key, set()).add(day_prefix)
                cohort_subject_slots.setdefault(key, []).append((day_prefix, slot_value))

        # Teacher gaps: avoid unnecessary idle periods between lessons.
        # TimeSlot IDs are HHMM labels, so convert them to real minutes before
        # comparing them. This avoids errors such as 09:50 -> 10:40 being
        # treated as a 90-minute gap.
        for slots in teacher_daily_blocks.values():
            slots.sort()
            for first, second in zip(slots, slots[1:]):
                if second - first > 100:
                    soft_conflicts += 1

        # Spread repeated subjects across the school week. One occurrence
        # per day is preferred for subjects with up to five weekly sessions.
        for key, days in cohort_subject_days.items():
            occurrences = len(cohort_subject_slots[key])
            if occurrences > 1:
                if len(days) == 1:
                    soft_conflicts += (occurrences - 1) * 2
                elif len(days) < min(occurrences, 5):
                    soft_conflicts += occurrences - len(days)

        # Avoid same-subject back-to-back teaching for a class. A double
        # period may still be necessary, so this remains a soft preference.
        for slots in cohort_subject_slots.values():
            by_day: Dict[str, List[int]] = {}
            for day, slot_value in slots:
                by_day.setdefault(day, []).append(slot_value)
            for day_slots in by_day.values():
                day_slots.sort()
                for first, second in zip(day_slots, day_slots[1:]):
                    if second - first <= 55:
                        soft_conflicts += 2

        # Avoid creating unnecessary gaps in a class's teaching day. This
        # keeps a class from receiving lessons at P1, P2, P6 while P3-P5 are
        # empty, when another placement is available.
        for slots in cohort_daily_slots.values():
            if len(slots) > 2:
                slots.sort()
                for first, second in zip(slots, slots[1:]):
                    if second - first > 110:
                        soft_conflicts += 1

        # Keep class teaching loads reasonably balanced across the week.
        for cohort in {gene.cohort_id for gene in chromosome.genes}:
            loads = [load for (c, _day), load in cohort_day_load.items() if c == cohort]
            if len(loads) > 1:
                spread = max(loads) - min(loads)
                soft_conflicts += max(0, spread - 2)

        # Avoid putting almost the whole school day on a single class where
        # there are other available days. More than six lessons in one day is
        # treated as a soft preference rather than a hard rule.
        for (_cohort, _day), load in cohort_day_load.items():
            if load > 6:
                soft_conflicts += load - 6

        chromosome.hard_conflicts = hard_conflicts
        chromosome.soft_conflicts = soft_conflicts
        chromosome.conflicting_gene_indices = conflicting_indices
        total_penalty = (hard_conflicts * cls.HARD_CONSTRAINT_PENALTY) + (soft_conflicts * cls.SOFT_CONSTRAINT_PENALTY)
        chromosome.fitness = 1.0 / (1.0 + total_penalty)
        return chromosome.fitness

    @staticmethod
    def _slot_parts(timeslot_id: str) -> Tuple[str, Optional[int]]:
        """Return day code and time in minutes since midnight."""
        try:
            day, value = timeslot_id.split('-', 1)
            raw = int(value)
            hours, minutes = divmod(raw, 100)
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                return day, hours * 60 + minutes
            return day, raw
        except (ValueError, AttributeError):
            return (timeslot_id.split('-', 1)[0] if '-' in timeslot_id else 'GEN', None)

@dataclass(frozen=True)
class RoomOption:
    """A candidate room the solver can place a lesson in."""
    room_id: str
    capacity: int
    is_lab: bool


@dataclass(frozen=True)
class LessonRequirement:
    """
    One lesson that needs a (teacher, room, timeslot) assigned to it.
    A ClassSubjectRequirement with periods_per_week=3 expands into 3 of these
    (session_index 0, 1, 2) so each weekly occurrence can land on a different day.
    """
    cohort_id: str
    subject_id: str
    session_index: int
    student_count: int
    is_lab_required: bool
    eligible_teacher_ids: Tuple[str, ...]  # teachers qualified for this subject

    @property
    def requirement_key(self) -> str:
        return f"{self.cohort_id}::{self.subject_id}::{self.session_index}"


class GeneticTimetableSolver:
    """
    Evolves a population of ScheduleChromosome candidates toward a
    conflict-free timetable using TimetableEvaluator as the fitness function.

    Pure Python / no Django dependency, so it can run and be unit-tested
    without a database.
    """

    def __init__(
        self,
        requirements: List[LessonRequirement],
        rooms: List[RoomOption],
        timeslot_ids: List[str],
        population_size: int = 60,
        generations: int = 200,
        mutation_rate: float = 0.15,
        elite_count: int = 4,
        tournament_size: int = 3,
        random_seed: Optional[int] = None,
    ):
        if not requirements:
            raise ValueError("Cannot generate a timetable with zero lesson requirements.")
        if not rooms:
            raise ValueError("Cannot generate a timetable with zero rooms configured.")
        if not timeslot_ids:
            raise ValueError("Cannot generate a timetable with zero timeslots configured.")

        self.requirements = requirements
        self.rooms = rooms
        self.timeslot_ids = timeslot_ids
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.elite_count = min(elite_count, population_size)
        self.tournament_size = tournament_size
        self._rng = random.Random(random_seed)

        self.lab_rooms = [r for r in rooms if r.is_lab]
        self.generations_run = 0

    # ---------------------------------------------------------------
    # Gene construction
    # ---------------------------------------------------------------
    def _pick_room(self, requirement: LessonRequirement) -> RoomOption:
        candidates = self.lab_rooms if requirement.is_lab_required else self.rooms
        if not candidates:
            raise ValueError(f"No suitable room is configured for {requirement.subject_id}.")
        big_enough = [r for r in candidates if r.capacity >= requirement.student_count]
        pool = big_enough or candidates
        return self._rng.choice(pool)

    def _pick_teacher(self, requirement: LessonRequirement) -> str:
        if requirement.eligible_teacher_ids:
            return self._rng.choice(requirement.eligible_teacher_ids)
        return "UNASSIGNED"

    def _random_gene(self, requirement: LessonRequirement) -> ClassGene:
        room = self._pick_room(requirement)
        return ClassGene(
            cohort_id=requirement.cohort_id,
            subject_id=requirement.subject_id,
            teacher_id=self._pick_teacher(requirement),
            room_id=room.room_id,
            timeslot_id=self._rng.choice(self.timeslot_ids),
            room_capacity=room.capacity,
            student_count=requirement.student_count,
            is_lab_required=requirement.is_lab_required,
            is_room_lab=room.is_lab,
        )

    def _candidate_gene(self, requirement: LessonRequirement, timeslot_id: str, teacher_id: str, room: RoomOption) -> ClassGene:
        return ClassGene(
            cohort_id=requirement.cohort_id,
            subject_id=requirement.subject_id,
            teacher_id=teacher_id,
            room_id=room.room_id,
            timeslot_id=timeslot_id,
            room_capacity=room.capacity,
            student_count=requirement.student_count,
            is_lab_required=requirement.is_lab_required,
            is_room_lab=room.is_lab,
        )

    def _greedy_score(self, gene: ClassGene, genes: List[ClassGene]) -> int:
        """Score a candidate using hard collisions plus distribution preferences."""
        score = 0
        day, slot = TimetableEvaluator._slot_parts(gene.timeslot_id)
        subject_days = set()
        subject_slots = []
        class_day_load = 0
        for existing in genes:
            if existing is None:
                continue
            if existing.teacher_id == gene.teacher_id and existing.timeslot_id == gene.timeslot_id:
                score += 100
            if existing.room_id == gene.room_id and existing.timeslot_id == gene.timeslot_id:
                score += 100
            if existing.cohort_id == gene.cohort_id and existing.timeslot_id == gene.timeslot_id:
                score += 100
            if existing.cohort_id == gene.cohort_id and existing.subject_id == gene.subject_id:
                old_day, old_slot = TimetableEvaluator._slot_parts(existing.timeslot_id)
                subject_days.add(old_day)
                if old_day == day and slot is not None and old_slot is not None:
                    if abs(slot - old_slot) <= 50:
                        score += 18
                    else:
                        score += 5
            if existing.cohort_id == gene.cohort_id and TimetableEvaluator._slot_parts(existing.timeslot_id)[0] == day:
                class_day_load += 1
                old_day, old_slot = TimetableEvaluator._slot_parts(existing.timeslot_id)
                if slot is not None and old_slot is not None:
                    distance = abs(slot - old_slot)
                    if distance > 110:
                        score += 3
        if subject_days and day in subject_days:
            score += 10
        if class_day_load >= 5:
            score += 6
        if gene.student_count > gene.room_capacity:
            score += 100
        if gene.is_lab_required and not gene.is_room_lab:
            score += 100
        return score

    def _create_greedy_individual(self) -> ScheduleChromosome:
        """Construct one low-conflict timetable before evolutionary search."""
        # Schedule the most constrained lessons first, but restore the
        # original requirement order before returning. Crossover/mutation
        # depend on every chromosome having the same gene index for the same
        # LessonRequirement.
        ordered = sorted(
            enumerate(self.requirements),
            key=lambda item: (len(item[1].eligible_teacher_ids), not item[1].is_lab_required, -item[1].student_count),
        )
        genes: List[Optional[ClassGene]] = [None] * len(self.requirements)
        for original_index, requirement in ordered:
            candidates = []
            teacher_pool = list(requirement.eligible_teacher_ids) or ['UNASSIGNED']
            room_pool = self.lab_rooms if requirement.is_lab_required else self.rooms
            for _ in range(min(48, max(12, len(self.timeslot_ids) * 2))):
                slot = self._rng.choice(self.timeslot_ids)
                teacher = self._rng.choice(teacher_pool)
                suitable_rooms = [r for r in room_pool if r.capacity >= requirement.student_count] or room_pool
                if not suitable_rooms:
                    continue
                room = self._rng.choice(suitable_rooms)
                candidate = self._candidate_gene(requirement, slot, teacher, room)
                candidates.append((self._greedy_score(candidate, genes), candidate))
                if candidates[-1][0] == 0:
                    break
            if not candidates:
                genes[original_index] = self._random_gene(requirement)
            else:
                candidates.sort(key=lambda item: item[0])
                # Randomly choose among the best few to retain population diversity.
                genes[original_index] = self._rng.choice(candidates[:min(3, len(candidates))])[1]
        chromosome = ScheduleChromosome([gene for gene in genes if gene is not None])
        TimetableEvaluator.calculate_fitness(chromosome)
        return chromosome

    def _create_individual(self) -> ScheduleChromosome:
        # Most initial candidates are constructive rather than completely
        # random. This dramatically reduces the 3-way collisions that the GA
        # otherwise spends hundreds of generations repairing.
        if self._rng.random() < 0.75:
            return self._create_greedy_individual()
        genes = [self._random_gene(req) for req in self.requirements]
        chromosome = ScheduleChromosome(genes)
        TimetableEvaluator.calculate_fitness(chromosome)
        return chromosome

    # ---------------------------------------------------------------
    # Genetic operators
    # ---------------------------------------------------------------
    def _tournament_select(self, population: List[ScheduleChromosome]) -> ScheduleChromosome:
        contenders = self._rng.sample(population, min(self.tournament_size, len(population)))
        return max(contenders, key=lambda c: c.fitness)

    def _crossover(self, parent_a: ScheduleChromosome, parent_b: ScheduleChromosome) -> ScheduleChromosome:
        # Requirements are in a fixed, aligned order across every individual,
        # so gene-by-gene uniform crossover is safe here.
        child_genes = [
            self._rng.choice([gene_a, gene_b])
            for gene_a, gene_b in zip(parent_a.genes, parent_b.genes)
        ]
        return ScheduleChromosome(child_genes)

    @staticmethod
    def _build_occupancy_maps(genes: List[ClassGene], skip_index: int) -> Tuple[Set[Tuple[str, str]], Set[Tuple[str, str]], Set[Tuple[str, str]]]:
        """(teacher_id, timeslot), (room_id, timeslot), (cohort_id, timeslot)
        pairs already claimed elsewhere in the chromosome, as O(1)-lookup
        sets, built once per mutation call rather than rescanned per
        candidate."""
        teacher_slots, room_slots, cohort_slots = set(), set(), set()
        for j, gene in enumerate(genes):
            if j == skip_index:
                continue
            teacher_slots.add((gene.teacher_id, gene.timeslot_id))
            room_slots.add((gene.room_id, gene.timeslot_id))
            cohort_slots.add((gene.cohort_id, gene.timeslot_id))
        return teacher_slots, room_slots, cohort_slots

    @staticmethod
    def _local_conflict_score(gene: ClassGene, occupancy: Tuple[Set, Set, Set]) -> int:
        """Cheap conflict count for one candidate gene against precomputed
        occupancy sets - O(1) per check instead of rescanning every other
        gene."""
        teacher_slots, room_slots, cohort_slots = occupancy
        score = 0
        if (gene.teacher_id, gene.timeslot_id) in teacher_slots:
            score += 1
        if (gene.room_id, gene.timeslot_id) in room_slots:
            score += 1
        if (gene.cohort_id, gene.timeslot_id) in cohort_slots:
            score += 1
        if gene.student_count > gene.room_capacity:
            score += 1
        if gene.is_lab_required and not gene.is_room_lab:
            score += 1
        return score

    def _repair_gene(
        self,
        requirement: LessonRequirement,
        occupancy: Tuple[Set, Set, Set],
        context_genes: List[ClassGene],
        samples: int = 24,
    ) -> ClassGene:
        """Repair a gene while preserving timetable quality.

        T3 originally selected repairs almost entirely on hard-conflict count.
        Once a chromosome reached zero hard conflicts, mutations could replace
        a good placement with a merely valid one. We now use the same
        distribution-aware score used during greedy construction while giving
        hard conflicts overwhelming priority.
        """
        best_gene, best_score = None, None
        for _ in range(samples):
            candidate = self._random_gene(requirement)
            local_hard = self._local_conflict_score(candidate, occupancy)
            score = (local_hard * 1000) + self._greedy_score(candidate, context_genes)
            if best_score is None or score < best_score:
                best_gene, best_score = candidate, score
                if best_score == 0:
                    break
        return best_gene

    def _mutate(self, chromosome: ScheduleChromosome) -> ScheduleChromosome:
        """
        Conflict-directed local repair: genes already flagged as part of a
        double-booking / capacity / lab mismatch get a new placement chosen
        by best-of-k local search with high probability; everything else
        keeps the normal low mutation_rate. Occupancy maps are built once
        per call (O(n)) rather than rescanned per candidate, which is what
        keeps this usable once a school has a few hundred lessons/week
        instead of a few dozen.
        """
        conflicting = chromosome.conflicting_gene_indices
        new_genes = list(chromosome.genes)
        for i, requirement in enumerate(self.requirements):
            probability = 0.98 if i in conflicting else self.mutation_rate
            if self._rng.random() < probability:
                occupancy = self._build_occupancy_maps(new_genes, i)
                context_genes = [gene for j, gene in enumerate(new_genes) if j != i]
                new_genes[i] = self._repair_gene(requirement, occupancy, context_genes)
        return ScheduleChromosome(new_genes)

    # ---------------------------------------------------------------
    # Main loop
    # ---------------------------------------------------------------
    def run(self) -> ScheduleChromosome:
        population = [self._create_individual() for _ in range(self.population_size)]
        population.sort(key=lambda c: c.fitness, reverse=True)
        best = population[0]

        stagnant = 0
        for generation in range(1, self.generations + 1):
            self.generations_run = generation

            # Once hard conflicts reach zero, continue briefly to improve the
            # timetable's distribution instead of stopping at the first valid
            # (but poorly balanced) schedule.
            if best.hard_conflicts == 0 and stagnant >= 30:
                break

            next_population = population[: self.elite_count]  # elitism

            while len(next_population) < self.population_size:
                parent_a = self._tournament_select(population)
                parent_b = self._tournament_select(population)
                child = self._crossover(parent_a, parent_b)
                TimetableEvaluator.calculate_fitness(child)  # populates conflicting_gene_indices for _mutate
                child = self._mutate(child)
                TimetableEvaluator.calculate_fitness(child)
                next_population.append(child)

            population = sorted(next_population, key=lambda c: c.fitness, reverse=True)
            if population[0].fitness > best.fitness:
                best = population[0]
                stagnant = 0
            else:
                stagnant += 1

        return best
