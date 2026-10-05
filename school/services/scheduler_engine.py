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
        self.workload_excess: int = 0


class TimetableEvaluator:
    """
    The main fitness evaluator that parses timetables and scores them.
    """
    # Penalty weights
    HARD_CONSTRAINT_PENALTY = 100
    SOFT_CONSTRAINT_PENALTY = 10
    DEFAULT_TEACHER_MAX_PERIODS = 25

    @classmethod
    def calculate_fitness(
        cls,
        chromosome: ScheduleChromosome,
        teacher_max_periods: Optional[Dict[str, int]] = None,
    ) -> float:
        """Evaluate hard constraints first, then timetable quality preferences."""
        hard_conflicts = 0
        soft_conflicts = 0
        conflicting_indices: Set[int] = set()

        teacher_claims: Dict[Tuple[str, str], int] = {}
        teacher_week_load: Dict[str, int] = {}
        teacher_max_periods = teacher_max_periods or {}
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

            teacher_week_load[gene.teacher_id] = teacher_week_load.get(gene.teacher_id, 0) + 1

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

        # Teacher workload is deliberately a SECONDARY objective. It is
        # tracked separately so workload balancing can break ties between
        # otherwise similar timetables without inflating the main soft
        # conflict count and degrading the proven T3.1 quality rules.
        workload_excess = 0
        for teacher_id, load in teacher_week_load.items():
            maximum = int(
                teacher_max_periods.get(
                    teacher_id, cls.DEFAULT_TEACHER_MAX_PERIODS
                )
                or cls.DEFAULT_TEACHER_MAX_PERIODS
            )
            if load > maximum:
                workload_excess += load - maximum

        chromosome.workload_excess = workload_excess

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

        # Keep teacher daily loads reasonably balanced. This is deliberately
        # soft: a teacher may legitimately have a full day, but the solver
        # should avoid concentrating all weekly lessons into a few days.
        for teacher in {gene.teacher_id for gene in chromosome.genes}:
            loads = []
            for day in {cls._slot_parts(g.timeslot_id)[0] for g in chromosome.genes}:
                loads.append(sum(1 for g in chromosome.genes if g.teacher_id == teacher and cls._slot_parts(g.timeslot_id)[0] == day))
            active = [x for x in loads if x > 0]
            if len(active) > 1:
                soft_conflicts += max(0, max(active) - min(active) - 2)

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
        base_fitness = 1.0 / (1.0 + total_penalty)
        # Workload only breaks ties; it must not outweigh a meaningful
        # improvement in the established timetable-quality objectives.
        chromosome.fitness = max(0.0, base_fitness - (workload_excess * 0.000001))
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
    """Fast, constraint-first school timetable generator.

    The old implementation mixed greedy placement, repair passes and genetic
    terminology.  For a school timetable this is unnecessary and could leave
    one or two conflicts after a long run.  This implementation uses a small
    randomized constructive search with bounded backtracking:

    * every class can occupy only one slot;
    * a teacher can teach only one class in a slot;
    * a room can host only one class in a slot;
    * lab subjects use only lab rooms;
    * room capacity is enforced;
    * no partially conflicting timetable is persisted by the service.

    ``population_size`` and ``generations`` remain accepted for compatibility
    with the existing service.  They now control the number of short search
    attempts rather than a genetic algorithm.
    """

    def __init__(
        self,
        requirements: List[LessonRequirement],
        rooms: List[RoomOption],
        timeslot_ids: List[str],
        population_size: int = 40,
        generations: int = 120,
        mutation_rate: float = 0.10,
        elite_count: int = 4,
        tournament_size: int = 3,
        random_seed: Optional[int] = None,
        teacher_max_periods: Optional[Dict[str, int]] = None,
        max_seconds: float = 30.0,
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
        self.population_size = max(4, int(population_size or 4))
        self.generations = max(1, int(generations or 1))
        self.mutation_rate = float(mutation_rate or 0.10)
        self._rng = random.Random(random_seed)
        self.teacher_max_periods = {
            str(k): int(v)
            for k, v in (teacher_max_periods or {}).items()
            if v is not None
        }
        self.max_seconds = max(5.0, float(max_seconds or 30.0))
        self.generations_run = 0

        self._room_pool_cache: Dict[Tuple[str, int, bool], List[RoomOption]] = {}
        for req in self.requirements:
            pool = self._room_pool(req)
            if not pool:
                kind = "lab" if req.is_lab_required else ""
                raise ValueError(
                    f"No suitable {kind} room is available for class {req.cohort_id}, "
                    f"subject {req.subject_id} ({req.student_count} students)."
                )

        self._ordered_requirement_indexes = self._order_requirements()

    def _room_pool(self, requirement: LessonRequirement) -> List[RoomOption]:
        key = (requirement.subject_id, requirement.student_count, bool(requirement.is_lab_required))
        if key in self._room_pool_cache:
            return self._room_pool_cache[key]
        candidates = [r for r in self.rooms if (not requirement.is_lab_required or r.is_lab)]
        suitable = [r for r in candidates if r.capacity >= requirement.student_count]
        suitable.sort(key=lambda r: (r.capacity, r.room_id))
        self._room_pool_cache[key] = suitable
        return suitable

    @staticmethod
    def _slot_day(slot_id: str) -> str:
        return slot_id.split('-', 1)[0] if '-' in slot_id else slot_id

    @staticmethod
    def _slot_value(slot_id: str) -> Optional[int]:
        return TimetableEvaluator._slot_parts(slot_id)[1]

    def _order_requirements(self) -> List[int]:
        """Place the hardest lessons first, while keeping occurrences together."""
        frequency = {}
        for req in self.requirements:
            key = (req.cohort_id, req.subject_id)
            frequency[key] = frequency.get(key, 0) + 1

        def key(index):
            req = self.requirements[index]
            pool_size = len(self._room_pool(req))
            return (
                len(req.eligible_teacher_ids),
                pool_size,
                0 if req.is_lab_required else 1,
                -req.student_count,
                -frequency[(req.cohort_id, req.subject_id)],
                req.cohort_id,
                req.subject_id,
                req.session_index,
            )

        return sorted(range(len(self.requirements)), key=key)

    def _candidate_score(
        self,
        req: LessonRequirement,
        teacher_id: str,
        slot_id: str,
        room: RoomOption,
        subject_days,
        subject_slots,
        class_day_load,
        teacher_day_load,
        teacher_load,
    ):
        day = self._slot_day(slot_id)
        value = self._slot_value(slot_id) or 0
        subject_key = (req.cohort_id, req.subject_id)
        existing_days = subject_days.get(subject_key, set())
        existing_slots = subject_slots.get(subject_key, [])
        class_load = class_day_load.get((req.cohort_id, day), 0)
        teacher_day = teacher_day_load.get((teacher_id, day), 0)
        teacher_total = teacher_load.get(teacher_id, 0)

        # Lower is better.  Subject distribution and balanced days are more
        # important than cosmetic room selection.
        same_day = 1 if day in existing_days else 0
        adjacent_subject = 0
        for existing_day, existing_value in existing_slots:
            if existing_day == day and abs(existing_value - value) <= 55:
                adjacent_subject += 1

        # Preserve larger rooms for large classes by preferring the smallest
        # suitable room.
        room_waste = room.capacity - req.student_count
        return (
            same_day,
            adjacent_subject,
            class_load,
            teacher_day,
            teacher_total,
            room_waste,
            value,
        )

    def _construct(self, seed_offset=0) -> Optional[ScheduleChromosome]:
        """Build one complete timetable without ever intentionally creating a conflict."""
        rng = random.Random(self._rng.randint(0, 2_000_000_000) + seed_offset)
        slots = list(self.timeslot_ids)
        rng.shuffle(slots)

        teacher_slots: Set[Tuple[str, str]] = set()
        room_slots: Set[Tuple[str, str]] = set()
        cohort_slots: Set[Tuple[str, str]] = set()
        subject_days = {}
        subject_slots = {}
        class_day_load = {}
        teacher_day_load = {}
        teacher_load = {}
        genes_by_index: Dict[int, ClassGene] = {}

        # A small bounded backtracking stack.  In normal demo data the first
        # pass completes; it exists to escape a greedy dead end near the end.
        history = []
        order = list(self._ordered_requirement_indexes)
        position = 0
        backtracks = 0
        max_backtracks = max(250, len(order) * 3)

        while position < len(order):
            index = order[position]
            req = self.requirements[index]
            candidates = []

            teachers = list(req.eligible_teacher_ids)
            rng.shuffle(teachers)
            teachers.sort(key=lambda t: teacher_load.get(t, 0))

            for teacher_id in teachers:
                for slot_id in slots:
                    if (teacher_id, slot_id) in teacher_slots:
                        continue
                    if (req.cohort_id, slot_id) in cohort_slots:
                        continue
                    pool = self._room_pool(req)
                    available = [r for r in pool if (r.room_id, slot_id) not in room_slots]
                    if not available:
                        continue
                    # Only the best room for this slot is needed.
                    room = min(
                        available,
                        key=lambda r: self._candidate_score(
                            req, teacher_id, slot_id, r, subject_days,
                            subject_slots, class_day_load, teacher_day_load, teacher_load
                        )
                    )
                    score = self._candidate_score(
                        req, teacher_id, slot_id, room, subject_days,
                        subject_slots, class_day_load, teacher_day_load, teacher_load
                    )
                    candidates.append((score, rng.random(), teacher_id, slot_id, room))

            if candidates:
                candidates.sort(key=lambda x: (x[0], x[1]))
                # Keep a little randomness among otherwise equivalent choices.
                pick_window = min(4, len(candidates))
                _, _, teacher_id, slot_id, room = candidates[rng.randrange(pick_window)]
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
                genes_by_index[index] = gene
                teacher_slots.add((teacher_id, slot_id))
                room_slots.add((room.room_id, slot_id))
                cohort_slots.add((req.cohort_id, slot_id))
                day = self._slot_day(slot_id)
                value = self._slot_value(slot_id) or 0
                skey = (req.cohort_id, req.subject_id)
                subject_days.setdefault(skey, set()).add(day)
                subject_slots.setdefault(skey, []).append((day, value))
                class_day_load[(req.cohort_id, day)] = class_day_load.get((req.cohort_id, day), 0) + 1
                teacher_day_load[(teacher_id, day)] = teacher_day_load.get((teacher_id, day), 0) + 1
                teacher_load[teacher_id] = teacher_load.get(teacher_id, 0) + 1
                history.append((index, gene))
                position += 1
                continue

            # No legal placement. Remove a few recent placements and retry.
            if not history or backtracks >= max_backtracks:
                return None

            rewind = min(3, len(history))
            for _ in range(rewind):
                old_index, old_gene = history.pop()
                old_req = self.requirements[old_index]
                del genes_by_index[old_index]
                teacher_slots.discard((old_gene.teacher_id, old_gene.timeslot_id))
                room_slots.discard((old_gene.room_id, old_gene.timeslot_id))
                cohort_slots.discard((old_gene.cohort_id, old_gene.timeslot_id))
                day = self._slot_day(old_gene.timeslot_id)
                value = self._slot_value(old_gene.timeslot_id) or 0
                skey = (old_req.cohort_id, old_req.subject_id)
                if skey in subject_slots:
                    try:
                        subject_slots[skey].remove((day, value))
                    except ValueError:
                        pass
                    if not subject_slots[skey]:
                        subject_slots.pop(skey, None)
                        subject_days.pop(skey, None)
                    else:
                        subject_days[skey] = {d for d, _ in subject_slots[skey]}
                class_key = (old_req.cohort_id, day)
                class_day_load[class_key] = class_day_load.get(class_key, 1) - 1
                if class_day_load[class_key] <= 0:
                    class_day_load.pop(class_key, None)
                teacher_key = (old_gene.teacher_id, day)
                teacher_day_load[teacher_key] = teacher_day_load.get(teacher_key, 1) - 1
                if teacher_day_load[teacher_key] <= 0:
                    teacher_day_load.pop(teacher_key, None)
                teacher_load[old_gene.teacher_id] = teacher_load.get(old_gene.teacher_id, 1) - 1
                if teacher_load[old_gene.teacher_id] <= 0:
                    teacher_load.pop(old_gene.teacher_id, None)
                position -= 1
            backtracks += 1

        genes = [genes_by_index[i] for i in range(len(self.requirements))]
        chromosome = ScheduleChromosome(genes)
        TimetableEvaluator.calculate_fitness(chromosome, self.teacher_max_periods)
        return chromosome

    def run(self) -> ScheduleChromosome:
        import time

        deadline = time.monotonic() + self.max_seconds
        # 20 short starts is still dramatically cheaper and more reliable than
        # hundreds of repair generations. Stop immediately once a legal schedule
        # is found.
        attempts = min(20, max(4, self.population_size // 2))
        best = None

        for attempt in range(attempts):
            if time.monotonic() >= deadline:
                break
            candidate = self._construct(seed_offset=attempt)
            self.generations_run = attempt + 1
            if candidate is None:
                continue
            if best is None or (
                candidate.hard_conflicts,
                candidate.soft_conflicts,
                candidate.workload_excess,
            ) < (
                best.hard_conflicts,
                best.soft_conflicts,
                best.workload_excess,
            ):
                best = candidate
            if candidate.hard_conflicts == 0 and candidate.soft_conflicts <= 12:
                break

        if best is None:
            # Return a diagnostic empty chromosome rather than inventing a
            # conflicting timetable. The service will report the failure.
            best = ScheduleChromosome([])
            best.hard_conflicts = 1
            best.soft_conflicts = 0
            best.fitness = 0.0

        TimetableEvaluator.calculate_fitness(best, self.teacher_max_periods)
        return best
