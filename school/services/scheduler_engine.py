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
        """
        Calculates hard and soft conflicts, then computes a normalized fitness score.
        A score of 1.0 represents a flawless, conflict-free schedule.
        """
        hard_conflicts = 0
        soft_conflicts = 0
        conflicting_indices: Set[int] = set()

        # (resource_id, timeslot_id) -> index of the gene that first claimed it.
        # A second gene claiming the same key is a double-booking; both the
        # new and the original gene get flagged so mutation can target them.
        teacher_claims: Dict[Tuple[str, str], int] = {}
        room_claims: Dict[Tuple[str, str], int] = {}
        cohort_claims: Dict[Tuple[str, str], int] = {}

        # Tracking for soft constraints
        teacher_daily_blocks: Dict[str, List[str]] = {}  # Track continuous blocks to flag gap friction

        for idx, gene in enumerate(chromosome.genes):
            t_slot = gene.timeslot_id

            # Extract day prefix (e.g., "MON" from "MON-0900") to track daily continuity
            day_prefix = t_slot.split('-')[0] if '-' in t_slot else 'GEN'
            teacher_daily_key = f"{gene.teacher_id}_{day_prefix}"
            teacher_daily_blocks.setdefault(teacher_daily_key, [])

            # ==========================================
            # 1. HARD CONSTRAINTS (Structural Violations)
            # ==========================================

            # Constraint A: Teacher Overlap
            teacher_key = (gene.teacher_id, t_slot)
            if teacher_key in teacher_claims:
                hard_conflicts += 1
                conflicting_indices.add(idx)
                conflicting_indices.add(teacher_claims[teacher_key])
            else:
                teacher_claims[teacher_key] = idx

            # Constraint B: Room Overlap
            room_key = (gene.room_id, t_slot)
            if room_key in room_claims:
                hard_conflicts += 1
                conflicting_indices.add(idx)
                conflicting_indices.add(room_claims[room_key])
            else:
                room_claims[room_key] = idx

            # Constraint C: Cohort Overlap (Student Group Overlap)
            cohort_key = (gene.cohort_id, t_slot)
            if cohort_key in cohort_claims:
                hard_conflicts += 1
                conflicting_indices.add(idx)
                conflicting_indices.add(cohort_claims[cohort_key])
            else:
                cohort_claims[cohort_key] = idx

            # Constraint D: Physical Capacity Check
            if gene.student_count > gene.room_capacity:
                hard_conflicts += 1
                conflicting_indices.add(idx)

            # Constraint E: Specialized Room Suitability
            if gene.is_lab_required and not gene.is_room_lab:
                hard_conflicts += 1
                conflicting_indices.add(idx)

            # ==========================================
            # 2. SOFT CONSTRAINTS (Preference Guidelines)
            # ==========================================

            # Collect slots for gap analysis
            teacher_daily_blocks[teacher_daily_key].append(t_slot)

        # Evaluate soft constraint gaps: Keep teachers' teaching days compact
        for teacher_day, slots in teacher_daily_blocks.items():
            if len(slots) > 1:
                # Sort timeslots by time component (e.g. "MON-0900" -> 900)
                try:
                    sorted_times = sorted([int(s.split('-')[1]) for s in slots if '-' in s])
                    for i in range(len(sorted_times) - 1):
                        # If difference between chronological classes is > 100 (more than a 1-hour slot)
                        # it indicates an unproductive, empty waiting block for the educator.
                        if (sorted_times[i + 1] - sorted_times[i]) > 100:
                            soft_conflicts += 1
                except (ValueError, IndexError):
                    # Fallback safely if custom slot naming configurations are used
                    pass

        # Save calculations on the object
        chromosome.hard_conflicts = hard_conflicts
        chromosome.soft_conflicts = soft_conflicts
        chromosome.conflicting_gene_indices = conflicting_indices

        # Compute normalized fitness (Equation scales smoothly down as conflict counts rise)
        total_penalty = (hard_conflicts * cls.HARD_CONSTRAINT_PENALTY) + (soft_conflicts * cls.SOFT_CONSTRAINT_PENALTY)
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

        self.lab_rooms = [r for r in rooms if r.is_lab] or rooms
        self.generations_run = 0

    # ---------------------------------------------------------------
    # Gene construction
    # ---------------------------------------------------------------
    def _pick_room(self, requirement: LessonRequirement) -> RoomOption:
        candidates = self.lab_rooms if requirement.is_lab_required else self.rooms
        # Prefer rooms with enough capacity; fall back to any room so a
        # gene always exists (the evaluator will penalize the mismatch).
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

    def _create_individual(self) -> ScheduleChromosome:
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

    def _repair_gene(self, requirement: LessonRequirement, occupancy: Tuple[Set, Set, Set], samples: int = 6) -> ClassGene:
        best_gene, best_score = None, None
        for _ in range(samples):
            candidate = self._random_gene(requirement)
            score = self._local_conflict_score(candidate, occupancy)
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
            probability = 0.9 if i in conflicting else self.mutation_rate
            if self._rng.random() < probability:
                occupancy = self._build_occupancy_maps(new_genes, i)
                new_genes[i] = self._repair_gene(requirement, occupancy)
        return ScheduleChromosome(new_genes)

    # ---------------------------------------------------------------
    # Main loop
    # ---------------------------------------------------------------
    def run(self) -> ScheduleChromosome:
        population = [self._create_individual() for _ in range(self.population_size)]
        population.sort(key=lambda c: c.fitness, reverse=True)
        best = population[0]

        for generation in range(1, self.generations + 1):
            self.generations_run = generation

            # A schedule with zero hard conflicts is usable (publishable);
            # soft conflicts are a preference, not a blocker, so we don't
            # keep grinding once the timetable is actually valid.
            if best.hard_conflicts == 0:
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

        return best
