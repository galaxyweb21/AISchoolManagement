# school/services/scheduler_engine.py
"""AI timetable scheduling engine.

The public classes in this module are intentionally kept stable because the
Django timetable service imports them directly.  T2 improves the search
strategy without changing the database models or the service API.
"""

import random
from typing import List, Dict, Tuple, Set, Optional
from dataclasses import dataclass


@dataclass(frozen=True)
class ClassGene:
    """Represents one scheduled weekly lesson."""
    cohort_id: str
    subject_id: str
    teacher_id: str
    room_id: str
    timeslot_id: str
    room_capacity: int
    student_count: int
    is_lab_required: bool
    is_room_lab: bool


class ScheduleChromosome:
    """A complete candidate timetable."""

    def __init__(self, genes: List[ClassGene]):
        self.genes = genes
        self.fitness: float = 0.0
        self.hard_conflicts: int = 0
        self.soft_conflicts: int = 0
        self.conflicting_gene_indices: Set[int] = set()


class TimetableEvaluator:
    """Scores a timetable using hard constraints and scheduling preferences."""

    HARD_CONSTRAINT_PENALTY = 100
    SOFT_CONSTRAINT_PENALTY = 10

    @staticmethod
    def _slot_parts(slot_id: str) -> Tuple[str, int]:
        """Return (day, start-minute) from the existing DAY-HHMM slot id."""
        try:
            day, raw_time = slot_id.split('-', 1)
            raw_time = raw_time[:4]
            hour = int(raw_time[:2])
            minute = int(raw_time[2:4])
            return day, hour * 60 + minute
        except (ValueError, IndexError):
            return 'GEN', 0

    @classmethod
    def calculate_fitness(cls, chromosome: ScheduleChromosome) -> float:
        hard_conflicts = 0
        soft_conflicts = 0
        conflicting_indices: Set[int] = set()

        teacher_claims: Dict[Tuple[str, str], int] = {}
        room_claims: Dict[Tuple[str, str], int] = {}
        cohort_claims: Dict[Tuple[str, str], int] = {}

        # Used for the preference layer.
        teacher_daily_blocks: Dict[Tuple[str, str], List[int]] = {}
        class_subject_days: Dict[Tuple[str, str, str], List[int]] = {}
        class_daily_load: Dict[Tuple[str, str], int] = {}

        for idx, gene in enumerate(chromosome.genes):
            t_slot = gene.timeslot_id
            day, minute = cls._slot_parts(t_slot)

            # -------------------------------------------------------
            # HARD CONSTRAINTS
            # -------------------------------------------------------
            teacher_key = (gene.teacher_id, t_slot)
            if teacher_key in teacher_claims:
                hard_conflicts += 1
                conflicting_indices.add(idx)
                conflicting_indices.add(teacher_claims[teacher_key])
            else:
                teacher_claims[teacher_key] = idx

            room_key = (gene.room_id, t_slot)
            if room_key in room_claims:
                hard_conflicts += 1
                conflicting_indices.add(idx)
                conflicting_indices.add(room_claims[room_key])
            else:
                room_claims[room_key] = idx

            cohort_key = (gene.cohort_id, t_slot)
            if cohort_key in cohort_claims:
                hard_conflicts += 1
                conflicting_indices.add(idx)
                conflicting_indices.add(cohort_claims[cohort_key])
            else:
                cohort_claims[cohort_key] = idx

            if gene.student_count > gene.room_capacity:
                hard_conflicts += 1
                conflicting_indices.add(idx)

            if gene.is_lab_required and not gene.is_room_lab:
                hard_conflicts += 1
                conflicting_indices.add(idx)

            # -------------------------------------------------------
            # SOFT-CONSTRAINT DATA
            # -------------------------------------------------------
            teacher_daily_blocks.setdefault((gene.teacher_id, day), []).append(minute)
            class_subject_days.setdefault((gene.cohort_id, gene.subject_id, day), []).append(minute)
            class_daily_load[(gene.cohort_id, day)] = class_daily_load.get((gene.cohort_id, day), 0) + 1

        # Teacher gaps: a teacher should not have unnecessarily large gaps
        # during the same day.  We use actual clock minutes rather than the
        # old HHMM arithmetic, so 08:50 -> 09:40 is correctly treated as 50m.
        for slots in teacher_daily_blocks.values():
            if len(slots) < 2:
                continue
            sorted_times = sorted(slots)
            for first, second in zip(sorted_times, sorted_times[1:]):
                if second - first > 70:
                    soft_conflicts += 1

        # Repeating the same subject more than once on a day is not normally
        # desirable.  It remains a preference, not a hard rule, because a
        # school may intentionally use double periods.
        for slots in class_subject_days.values():
            if len(slots) > 1:
                soft_conflicts += (len(slots) - 1) * 2
                sorted_times = sorted(slots)
                for first, second in zip(sorted_times, sorted_times[1:]):
                    # 50- or 60-minute adjacency is treated as a likely
                    # double period and gets a smaller additional penalty.
                    if 0 < second - first <= 65:
                        soft_conflicts += 1

        # Avoid concentrating too many lessons into one class's day.
        for daily_load in class_daily_load.values():
            if daily_load > 6:
                soft_conflicts += daily_load - 6

        chromosome.hard_conflicts = hard_conflicts
        chromosome.soft_conflicts = soft_conflicts
        chromosome.conflicting_gene_indices = conflicting_indices

        total_penalty = (
            hard_conflicts * cls.HARD_CONSTRAINT_PENALTY
            + soft_conflicts * cls.SOFT_CONSTRAINT_PENALTY
        )
        chromosome.fitness = 1.0 / (1.0 + total_penalty)
        return chromosome.fitness


@dataclass(frozen=True)
class RoomOption:
    """A candidate room the solver can place a lesson in."""
    room_id: str
    capacity: int
    is_lab: bool


@dataclass(frozen=True)
class LessonRequirement:
    """One weekly occurrence of a class+subject requirement."""
    cohort_id: str
    subject_id: str
    session_index: int
    student_count: int
    is_lab_required: bool
    eligible_teacher_ids: Tuple[str, ...]

    @property
    def requirement_key(self) -> str:
        return f"{self.cohort_id}::{self.subject_id}::{self.session_index}"


class GeneticTimetableSolver:
    """Genetic timetable solver with conflict-aware construction and repair."""

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

        self.requirements = list(requirements)
        self.rooms = list(rooms)
        self.timeslot_ids = list(timeslot_ids)
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.elite_count = min(elite_count, population_size)
        self.tournament_size = tournament_size
        self._rng = random.Random(random_seed)
        self.lab_rooms = [r for r in self.rooms if r.is_lab]
        self.generations_run = 0
        # Once a feasible timetable is found, keep a short optimization
        # window so T2 can improve soft distribution without turning every
        # generation request into a full 300-generation run.
        self.feasible_optimization_generations = 25

        # A hard failure is preferable to deliberately creating impossible
        # genes.  Readiness normally catches this first, but keeping the
        # solver defensive makes it safe for management commands/tests too.
        if any(r.is_lab_required for r in self.requirements) and not self.lab_rooms:
            raise ValueError("At least one laboratory room is required by the timetable but none is configured.")

    # ---------------------------------------------------------------
    # Slot helpers
    # ---------------------------------------------------------------
    @staticmethod
    def _slot_parts(slot_id: str) -> Tuple[str, int]:
        return TimetableEvaluator._slot_parts(slot_id)

    def _slot_sort_key(self, slot_id: str) -> Tuple[int, int]:
        day, minute = self._slot_parts(slot_id)
        day_order = {'MON': 0, 'TUE': 1, 'WED': 2, 'THU': 3, 'FRI': 4}
        return day_order.get(day, 99), minute

    # ---------------------------------------------------------------
    # Candidate construction
    # ---------------------------------------------------------------
    def _room_candidates(self, requirement: LessonRequirement) -> List[RoomOption]:
        rooms = self.lab_rooms if requirement.is_lab_required else self.rooms
        suitable = [r for r in rooms if r.capacity >= requirement.student_count]
        # Readiness should normally make this impossible, but preserve the
        # previous fallback behaviour for unusual direct solver calls.
        return suitable or rooms

    def _pick_teacher(self, requirement: LessonRequirement, teacher_load: Optional[Dict[str, int]] = None) -> str:
        if not requirement.eligible_teacher_ids:
            return 'UNASSIGNED'
        if not teacher_load:
            return self._rng.choice(requirement.eligible_teacher_ids)
        minimum = min(teacher_load.get(t, 0) for t in requirement.eligible_teacher_ids)
        candidates = [t for t in requirement.eligible_teacher_ids if teacher_load.get(t, 0) == minimum]
        return self._rng.choice(candidates)

    def _pick_room(self, requirement: LessonRequirement) -> RoomOption:
        candidates = self._room_candidates(requirement)
        # Prefer the smallest suitable room to preserve larger rooms for
        # larger classes, while keeping a little randomness for population
        # diversity.
        minimum_capacity = min(r.capacity for r in candidates)
        near_minimum = [r for r in candidates if r.capacity <= minimum_capacity + 10]
        return self._rng.choice(near_minimum or candidates)

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

    @staticmethod
    def _build_occupancy_maps(
        genes: List[ClassGene], skip_index: int
    ) -> Tuple[Set[Tuple[str, str]], Set[Tuple[str, str]], Set[Tuple[str, str]]]:
        teacher_slots, room_slots, cohort_slots = set(), set(), set()
        for j, gene in enumerate(genes):
            if j == skip_index:
                continue
            teacher_slots.add((gene.teacher_id, gene.timeslot_id))
            room_slots.add((gene.room_id, gene.timeslot_id))
            cohort_slots.add((gene.cohort_id, gene.timeslot_id))
        return teacher_slots, room_slots, cohort_slots

    @staticmethod
    def _local_conflict_score(
        gene: ClassGene,
        occupancy: Tuple[Set, Set, Set],
    ) -> int:
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

    def _soft_candidate_score(self, gene: ClassGene, genes: List[ClassGene], skip_index: int) -> float:
        """Lower is better. Scores only preferences; hard conflicts are separate."""
        score = 0.0
        day, minute = self._slot_parts(gene.timeslot_id)
        class_day_count = 0
        same_subject_same_day = 0
        teacher_day_times: List[int] = []
        class_day_load = 0

        for idx, other in enumerate(genes):
            if idx == skip_index:
                continue
            other_day, other_minute = self._slot_parts(other.timeslot_id)
            if other_day != day:
                continue

            if other.cohort_id == gene.cohort_id:
                class_day_load += 1
                if other.subject_id == gene.subject_id:
                    same_subject_same_day += 1

            if other.teacher_id == gene.teacher_id:
                teacher_day_times.append(other_minute)

        class_day_count = class_day_load
        if same_subject_same_day:
            # Strongly prefer another day for repeated weekly sessions.
            score += same_subject_same_day * 8

            # A likely double period is less desirable than a separate slot.
            for other_minute in teacher_day_times:
                if abs(other_minute - minute) <= 65:
                    score += 2

        if class_day_count >= 6:
            score += (class_day_count - 5) * 2

        if teacher_day_times:
            nearest_gap = min(abs(t - minute) for t in teacher_day_times)
            if nearest_gap > 70:
                score += 1

        return score

    def _construct_individual(self) -> ScheduleChromosome:
        """Build a mostly conflict-free chromosome before genetic evolution.

        The old solver created every gene completely at random. With only a
        few dozen weekly slots that made the first generation heavily
        double-booked and forced mutation to spend most of the run repairing
        avoidable clashes. T2 starts with a feasible greedy schedule instead.
        """
        genes: List[Optional[ClassGene]] = [None] * len(self.requirements)
        teacher_slots: Set[Tuple[str, str]] = set()
        room_slots: Set[Tuple[str, str]] = set()
        cohort_slots: Set[Tuple[str, str]] = set()
        teacher_load: Dict[str, int] = {}

        # Interleave repeated sessions so one class/subject does not consume
        # a cluster of slots before other subjects receive a placement.
        order = sorted(
            range(len(self.requirements)),
            key=lambda i: (
                self.requirements[i].session_index,
                0 if self.requirements[i].is_lab_required else 1,
                -len(self.requirements[i].eligible_teacher_ids),
            ),
        )

        for index in order:
            req = self.requirements[index]
            room_options = self._room_candidates(req)
            teachers = list(req.eligible_teacher_ids) or ['UNASSIGNED']
            self._rng.shuffle(teachers)

            candidates: List[Tuple[float, ClassGene]] = []
            slots = list(self.timeslot_ids)
            self._rng.shuffle(slots)

            for slot_id in slots:
                # Cohort overlap is never useful, so reject this slot early.
                if (req.cohort_id, slot_id) in cohort_slots:
                    continue

                # Try all eligible teachers but keep the least-loaded teacher
                # first. This also improves workload balance when co-teachers
                # exist.
                teachers_for_slot = sorted(teachers, key=lambda t: teacher_load.get(t, 0))
                for teacher_id in teachers_for_slot:
                    if (teacher_id, slot_id) in teacher_slots:
                        continue

                    # Prefer the smallest suitable room that is free.
                    free_rooms = [r for r in room_options if (r.room_id, slot_id) not in room_slots]
                    if not free_rooms:
                        continue
                    min_capacity = min(r.capacity for r in free_rooms)
                    best_rooms = [r for r in free_rooms if r.capacity <= min_capacity + 10]
                    room = self._rng.choice(best_rooms or free_rooms)

                    gene = ClassGene(
                        cohort_id=req.cohort_id,
                        subject_id=req.subject_id,
                        teacher_id=teacher_id,
                        room_id=room.room_id,
                        timeslot_id=slot_id,
                        room_capacity=room.capacity,
                        student_count=req.student_count,
                        is_lab_required=req.is_lab_required,
                        is_room_lab=room.is_lab,
                    )

                    score = self._soft_candidate_score(
                        gene,
                        [g for g in genes if g is not None],
                        -1,
                    )
                    # Small random noise preserves genetic diversity while
                    # strongly preferring the cleaner placements.
                    score += self._rng.random() * 0.35
                    candidates.append((score, gene))

                # Once we have several good candidates from this slot, there
                # is no need to inspect every teacher/room combination.
                if len(candidates) >= 24:
                    break

            if candidates:
                candidates.sort(key=lambda item: item[0])
                # Choose from the best few rather than always taking #1.
                chosen_score, gene = self._rng.choice(candidates[: min(4, len(candidates))])
            else:
                # Extremely constrained direct solver calls can still reach
                # this path. Fall back to a random valid-looking gene and let
                # the evaluator/repair process handle it.
                gene = self._random_gene(req)

            genes[index] = gene
            teacher_slots.add((gene.teacher_id, gene.timeslot_id))
            room_slots.add((gene.room_id, gene.timeslot_id))
            cohort_slots.add((gene.cohort_id, gene.timeslot_id))
            teacher_load[gene.teacher_id] = teacher_load.get(gene.teacher_id, 0) + 1

        chromosome = ScheduleChromosome([g for g in genes if g is not None])
        TimetableEvaluator.calculate_fitness(chromosome)
        return chromosome

    def _create_individual(self) -> ScheduleChromosome:
        return self._construct_individual()

    # ---------------------------------------------------------------
    # Genetic operators
    # ---------------------------------------------------------------
    def _tournament_select(self, population: List[ScheduleChromosome]) -> ScheduleChromosome:
        contenders = self._rng.sample(population, min(self.tournament_size, len(population)))
        return max(contenders, key=lambda c: c.fitness)

    def _crossover(
        self,
        parent_a: ScheduleChromosome,
        parent_b: ScheduleChromosome,
    ) -> ScheduleChromosome:
        child_genes = [
            self._rng.choice([gene_a, gene_b])
            for gene_a, gene_b in zip(parent_a.genes, parent_b.genes)
        ]
        return ScheduleChromosome(child_genes)

    def _repair_gene(
        self,
        requirement: LessonRequirement,
        occupancy: Tuple[Set, Set, Set],
        existing_genes: Optional[List[ClassGene]] = None,
        skip_index: int = -1,
        samples: int = 14,
    ) -> ClassGene:
        best_gene = None
        best_key = None

        teacher_slots, room_slots, cohort_slots = occupancy
        room_options = self._room_candidates(requirement)
        teachers = list(requirement.eligible_teacher_ids) or ['UNASSIGNED']

        for _ in range(samples):
            slot_id = self._rng.choice(self.timeslot_ids)
            teacher_id = self._rng.choice(teachers)
            free_rooms = [r for r in room_options if (r.room_id, slot_id) not in room_slots]
            room = self._rng.choice(free_rooms or room_options)
            gene = ClassGene(
                cohort_id=requirement.cohort_id,
                subject_id=requirement.subject_id,
                teacher_id=teacher_id,
                room_id=room.room_id,
                timeslot_id=slot_id,
                room_capacity=room.capacity,
                student_count=requirement.student_count,
                is_lab_required=requirement.is_lab_required,
                is_room_lab=room.is_lab,
            )
            hard = self._local_conflict_score(gene, occupancy)
            soft = self._soft_candidate_score(
                gene,
                existing_genes or [],
                skip_index,
            )
            key = (hard, soft, self._rng.random())
            if best_key is None or key < best_key:
                best_key = key
                best_gene = gene
                if hard == 0 and soft == 0:
                    break

        return best_gene or self._random_gene(requirement)

    def _mutate(self, chromosome: ScheduleChromosome) -> ScheduleChromosome:
        conflicting = chromosome.conflicting_gene_indices
        new_genes = list(chromosome.genes)

        for i, requirement in enumerate(self.requirements):
            probability = 0.92 if i in conflicting else self.mutation_rate
            if self._rng.random() < probability:
                occupancy = self._build_occupancy_maps(new_genes, i)
                new_genes[i] = self._repair_gene(
                    requirement,
                    occupancy,
                    existing_genes=new_genes,
                    skip_index=i,
                )

        return ScheduleChromosome(new_genes)

    # ---------------------------------------------------------------
    # Main loop
    # ---------------------------------------------------------------
    def run(self) -> ScheduleChromosome:
        population = [self._create_individual() for _ in range(self.population_size)]
        population.sort(key=lambda c: c.fitness, reverse=True)
        best = population[0]

        feasible_since = None

        for generation in range(1, self.generations + 1):
            self.generations_run = generation

            if best.hard_conflicts == 0:
                if feasible_since is None:
                    feasible_since = generation
                elif generation - feasible_since >= self.feasible_optimization_generations:
                    break

            next_population = population[: self.elite_count]

            while len(next_population) < self.population_size:
                parent_a = self._tournament_select(population)
                parent_b = self._tournament_select(population)
                child = self._crossover(parent_a, parent_b)
                TimetableEvaluator.calculate_fitness(child)
                child = self._mutate(child)
                TimetableEvaluator.calculate_fitness(child)
                next_population.append(child)

            population = sorted(next_population, key=lambda c: c.fitness, reverse=True)
            if population[0].fitness > best.fitness:
                best = population[0]

        return best
