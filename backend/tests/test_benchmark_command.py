import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_benchmark_refuses_normal_database_without_touching_data():
    with pytest.raises(CommandError, match="bench_"):
        call_command("benchmark_inventory", rows=100_000)
