"""Metrics collection for performance monitoring."""

import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class OperationMetrics:
    """Metrics for a specific operation."""
    name: str
    count: int = 0
    total_duration: float = 0.0
    min_duration: Optional[float] = None
    max_duration: Optional[float] = None
    error_count: int = 0
    last_error: Optional[str] = None
    
    @property
    def avg_duration(self) -> float:
        """Average duration per operation."""
        return self.total_duration / self.count if self.count > 0 else 0.0
    
    @property
    def success_rate(self) -> float:
        """Success rate (0.0 to 1.0)."""
        return (self.count - self.error_count) / self.count if self.count > 0 else 1.0


@dataclass 
class PipelineMetrics:
    """Comprehensive metrics for the entire pipeline."""
    start_time: datetime = field(default_factory=datetime.now)
    operations: Dict[str, OperationMetrics] = field(default_factory=dict)
    counters: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    def get_operation(self, name: str) -> OperationMetrics:
        """Get or create operation metrics."""
        if name not in self.operations:
            self.operations[name] = OperationMetrics(name)
        return self.operations[name]
    
    @contextmanager
    def track_operation(self, operation_name: str):
        """Context manager to track operation duration and success/failure."""
        op = self.get_operation(operation_name)
        start_time = time.time()
        
        try:
            yield
            # Success case
            duration = time.time() - start_time
            op.count += 1
            op.total_duration += duration
            
            if op.min_duration is None or duration < op.min_duration:
                op.min_duration = duration
            if op.max_duration is None or duration > op.max_duration:
                op.max_duration = duration
                
        except Exception as e:
            # Error case
            duration = time.time() - start_time
            op.count += 1
            op.total_duration += duration
            op.error_count += 1
            op.last_error = str(e)
            raise
    
    def increment(self, counter_name: str, value: int = 1) -> None:
        """Increment a counter."""
        self.counters[counter_name] += value
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all metrics."""
        total_duration = (datetime.now() - self.start_time).total_seconds()
        
        return {
            "total_duration_seconds": total_duration,
            "operations": {
                name: {
                    "count": op.count,
                    "avg_duration_ms": op.avg_duration * 1000,
                    "min_duration_ms": op.min_duration * 1000 if op.min_duration else None,
                    "max_duration_ms": op.max_duration * 1000 if op.max_duration else None,
                    "success_rate": op.success_rate,
                    "error_count": op.error_count,
                    "last_error": op.last_error,
                }
                for name, op in self.operations.items()
            },
            "counters": dict(self.counters),
        }


# Global metrics instance
_metrics = PipelineMetrics()


def get_metrics() -> PipelineMetrics:
    """Get the global metrics instance."""
    return _metrics


def reset_metrics() -> None:
    """Reset all metrics (useful for testing)."""
    global _metrics
    _metrics = PipelineMetrics()