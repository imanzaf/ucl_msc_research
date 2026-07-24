"""Deterministically compute and validate all scenario arithmetic."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List

from src.data_models.scenarios import ComputedNumericValue, NumericCalculation, NumericInput, NumericOperation, NumericRegistry


def _calculate(
    operation: NumericOperation,
    operands: List[Decimal],
    operand_units: List[str],
    expected_unit: str,
) -> Decimal:
    """Apply one supported deterministic operation to typed decimal operands."""
    if operation == NumericOperation.ADD:
        return sum(operands, Decimal("0"))
    if operation == NumericOperation.SUBTRACT:
        if len(operands) != 2:
            raise ValueError("subtract requires exactly two operands")
        return operands[0] - operands[1]
    if operation == NumericOperation.MULTIPLY:
        if len(operands) < 2:
            raise ValueError("multiply requires at least two operands")
        result = Decimal("1")
        output_is_percentage = "percent" in expected_unit.casefold()
        for operand, unit in zip(operands, operand_units):
            value = operand
            if not output_is_percentage and "percent" in unit.casefold():
                value /= Decimal("100")
            result *= value
        return result
    if operation == NumericOperation.DIVIDE:
        if len(operands) != 2:
            raise ValueError("divide requires exactly two operands")
        if operands[1] == 0:
            raise ValueError("division by zero")
        return operands[0] / operands[1]
    if operation == NumericOperation.PERCENTAGE_CHANGE:
        if len(operands) != 2:
            raise ValueError("percentage_change requires old and new values")
        if operands[0] == 0:
            raise ValueError("percentage change baseline cannot be zero")
        return (operands[1] - operands[0]) / operands[0] * Decimal("100")
    if operation == NumericOperation.ANNUALISED_TOTAL:
        if len(operands) != 1:
            raise ValueError("annualised_total requires one monthly operand")
        return operands[0] * Decimal("12")
    raise ValueError(f"unsupported operation: {operation}")


def compute_numeric_registry(inputs: List[NumericInput], calculations: List[NumericCalculation]) -> NumericRegistry:
    """Resolve calculations in declared order and return a typed numeric registry."""
    values: Dict[str, Decimal] = {item.value_id: item.value for item in inputs}
    units: Dict[str, str] = {item.value_id: item.unit for item in inputs}
    computed: List[ComputedNumericValue] = []
    for calculation in calculations:
        missing = [value_id for value_id in calculation.operand_value_ids if value_id not in values]
        if missing:
            raise ValueError("numeric calculation has unresolved operands: " + ", ".join(missing))
        operands = [values[value_id] for value_id in calculation.operand_value_ids]
        operand_units = [units[value_id] for value_id in calculation.operand_value_ids]
        quantum = Decimal("1").scaleb(-calculation.decimal_places)
        result = _calculate(
            calculation.operation,
            operands,
            operand_units,
            calculation.expected_unit,
        ).quantize(quantum, rounding=ROUND_HALF_UP)
        values[calculation.output_value_id] = result
        units[calculation.output_value_id] = calculation.expected_unit
        computed.append(
            ComputedNumericValue(
                value_id=calculation.output_value_id,
                value=result,
                unit=calculation.expected_unit,
                calculation=calculation,
            )
        )
    return NumericRegistry(schema_version="2.0.0", inputs=inputs, calculations=calculations, computed_values=computed)
