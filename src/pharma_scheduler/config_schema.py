"""Configuration schema validation.

This module defines the expected structure of the configuration using dataclasses.
It provides a robust way to validate instance.yaml and catch typos early.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import date
import sys

@dataclass
class ServiceCycleConfig:
    anchor_monday: str
    cycle_weeks: int
    service_week_in_cycle: int

@dataclass
class WorkerConfig:
    id: str
    name: str
    groups: List[str] = field(default_factory=list)

@dataclass
class ShiftDemandRules:
    hard_min: int = 1
    penalty: int = 0

@dataclass
class ConstraintsConfig:
    min_daily_rest_hours: int
    weekend_coupling_enabled: bool = True
    sunday_compensation_enabled: bool = True
    weekly_rest_penalty_enabled: bool = True
    symmetry_breaking_enabled: bool = True

@dataclass
class FairnessConfig:
    weekend_minutes: int = 0
    holiday_minutes: int = 0
    weekday_excess: int = 0
    shift_counts: int = 0

@dataclass
class ObjectiveConfig:
    saturday_weight: int
    sunday_weight: int
    holiday_weight: int
    weekday_excess_weight: int
    weekly_rest_penalty: int
    sunday_next_weekend_penalty: int
    penalty_sunday_comp_delayed: int
    fairness: FairnessConfig
    
    # Optional penalties
    penalty_low_coverage_m: int = 0 # Deprecated/legacy support
    penalty_low_coverage_i: int = 0 # Deprecated/legacy support

@dataclass
class SolverConfig:
    time_limit_seconds: int = 300
    num_search_workers: int = 8
    log_search_progress: bool = True
    print_response_stats: bool = False
    random_seed: Optional[int] = None

@dataclass
class InstanceConfig:
    """Root configuration object."""
    report_start: str
    report_end: str
    buffer_days: int
    locale: str
    
    service_cycle: ServiceCycleConfig
    workers: List[WorkerConfig]
    demand: Dict[str, Dict[str, int]]
    constraints: ConstraintsConfig
    objective: ObjectiveConfig
    solver: SolverConfig
    
    demand_rules: Dict[str, ShiftDemandRules] = field(default_factory=dict)
    shifts: List[Dict[str, Any]] = field(default_factory=list) # Populated from shifts.yaml

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InstanceConfig':
        """Robustly parser dictionary into typed config object."""
        try:
            # Parse nested objects
            service_cycle = ServiceCycleConfig(**data['service_cycle'])
            
            workers = [WorkerConfig(**w) for w in data['workers']]
            
            constraints = ConstraintsConfig(**data['constraints'])
            
            # Handle nested fairness config
            fairness_data = data['objective'].pop('fairness', {})
            fairness = FairnessConfig(**fairness_data)
            objective = ObjectiveConfig(fairness=fairness, **data['objective'])
            
            solver = SolverConfig(**data.get('solver', {}))
            
            # Parse demand rules
            demand_rules = {}
            if 'demand_rules' in data:
                for shift, rules in data['demand_rules'].items():
                    demand_rules[shift] = ShiftDemandRules(**rules)

            return cls(
                report_start=data['report_start'],
                report_end=data['report_end'],
                buffer_days=data.get('buffer_days', 14),
                locale=data.get('locale', 'PT'),
                service_cycle=service_cycle,
                workers=workers,
                demand=data['demand'],
                constraints=constraints,
                objective=objective,
                solver=solver,
                demand_rules=demand_rules,
                shifts=data.get('shifts', [])
            )
        except TypeError as e:
            print(f"Configuration Error: {e}")
            print("Please check your instance.yaml for missing or misspelled keys.")
            sys.exit(1)
        except Exception as e:
            print(f"Configuration Error: {e}")
            sys.exit(1)

    def to_dict(self) -> Dict[str, Any]:
        """Convert back to dictionary for compatibility with existing code."""
        # This is a basic implementation, in a real scenario we might use asdict
        # but here we need to match exact structure expected by model/solver
        # or we just update model/solver to use the object.
        # For this refactor, we will maintain dict compatibility.
        from dataclasses import asdict
        return asdict(self)
