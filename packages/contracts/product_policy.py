"""Scope of new product executions; historical request shapes remain readable."""

from .check_experiment_contract import ContractError


def validate_product_scope(request):
    """Reject unsupported choices without changing any requested value."""
    hardware = request["hardware"]
    if hardware["tile_size"] != 64:
        raise ContractError("New experiments require a 64x64 array.", "hardware.tile_size", "outside_product_scope")
    expected_order = "adc_then_subtract" if request["effects"]["adc"] else None
    if hardware["adc_order"] != expected_order:
        raise ContractError("ADC order must be adc_then_subtract when on and null when off.",
                            "hardware.adc_order", "outside_product_scope")
    if hardware["preset_id"] is not None:
        raise ContractError("PPA presets are outside the current product scope.",
                            "hardware.preset_id", "outside_product_scope")
    if request["engines"]["ppa"] != "off":
        raise ContractError("PPA is outside the current product scope.",
                            "engines.ppa", "outside_product_scope")
