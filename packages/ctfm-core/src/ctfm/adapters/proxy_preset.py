"""The ``assumed_proxy`` NeuroSim preset that docs/spec/08-hardware-baseline.md fixes.

Every value below is either stated in spec 08 (sections 2, 3, 5) or derived from a stated constraint; ``basis``
records which, per field. The result is a *conditional cost estimate of a virtual analog circuit that uses the measured
conductances* -- not a CTFM device or chip, and ``validated_for_ctfm`` stays False. Nothing here is a device-team value
and nothing is copied from NeuroSim's stock SRAM defaults: where a stock default happens to equal the spec value
(22 nm, 300 K, LSTP, 0.55 V, 10 ns, 1.1 V, 4Fx12F) that is a coincidence the spec relies on, and it is stated explicitly
so the build never depends on the stock default silently.
"""
from __future__ import annotations

PRESET_ID = "ctfm_assumed_proxy_v1"
TILE_SIZES = (64, 128, 256)
LABEL = ("측정 전도도를 적용한 선형 등가 회로의 조건부 비용 추정 (assumed_proxy). "
         "실제 제작 CTFM 가속기의 성능이 아니며 CTFM 회로로 검증되지 않았다.")

BASIS = {
    "technode_nm": "spec 08 §2: 주변 CMOS 22nm (가상 주변회로, 실측 소자 공정 아님)",
    "temperature_k": "spec 08 §2: 300K",
    "device_roadmap": "spec 08 §2: LSTP",
    "read_voltage_v": "spec 08 §3: 비용 기준 readVoltage 0.55V; 측정 VDS 0.1V와 분리, 선형 저항 근사(전압 전이 검증 없음)",
    "read_pulse_width_s": "spec 08 §3: 가상 read excitation 10ns; 측정 읽기 구간 1ms나 write pulse에서 가져온 값이 아님",
    "read_pulse_width_source": "spec 08 §3",
    "access_type": "spec 08 §3: NeuroSim RRAM + CMOS access 읽기 계산 경로",
    "access_voltage_v": "spec 08 §3: access gate 1.1V (실제 read VGS 아님)",
    "cell_footprint_f": "spec 08 §3: 엔진 4F×12F (실제 셀 치수 아님)",
    "memcell_type": "spec 08 §3: measured_conductance_1t1r_proxy_v1 — CTFM을 RRAM으로 동일시하지 않음",
    "cell_bit": "derived, spec 08 §5: 가중치 bit slicing 없음, engine cellBit로 물리 column 수가 늘지 않게 → ceil(synapse_bit/cell_bit)=1",
    "synapse_bit": "derived, spec 08 §5 + 기존 trace: 엔진에 제시하는 가중치 정밀도 8 (weight 파일 정규화와 동일)",
    "sub_array": "요청의 배열 크기(64/128/256) — 사용자 선택이며 preset 고정값이 아님",
    "parallel_rows": "derived: 다중레벨 셀은 부분 병렬 읽기 불가(upstream README) → 배열 전체 병렬 read (operationmode 2)",
    "adc_architecture": "spec 08 §2: current-mode MLSA",
    "columns_per_adc": "spec 08 §2, §5: 경로별 8열 공유",
    "interconnect": "spec 08 §2: XY bus",
    "input_precision_bits": "spec 08 §2: unsigned 8 bit, bit serial, LSB부터 8회",
}


def proxy_preset(tile_size):
    """The fixed spec-08 preset for one requested physical array size."""
    if isinstance(tile_size, bool) or tile_size not in TILE_SIZES:
        raise ValueError("assumed_proxy supports array sizes " + ", ".join(map(str, TILE_SIZES)))
    return {
        "preset_id": PRESET_ID, "model_status": "assumed_proxy", "label": LABEL,
        "validated_for_ctfm": False, "assumed_equivalent_circuit": True,
        "technode_nm": 22, "temperature_k": 300, "device_roadmap": "LSTP",
        "read_voltage_v": 0.55, "read_pulse_width_s": 1e-8,
        "read_pulse_width_source": "spec_08_virtual_read_excitation",
        "access_type": "CMOS_access", "access_voltage_v": 1.1, "cell_footprint_f": [4, 12],
        "memcell_type": "RRAM", "cell_bit": 8, "synapse_bit": 8,
        "sub_array": tile_size, "parallel_rows": tile_size,
        "adc_architecture": "MLSA current mode", "columns_per_adc": 8, "interconnect": "XY bus",
        "input_precision_bits": 8, "measurement_vds_v": 0.1,
        "basis": dict(BASIS),
        "excluded_by_scope": ["write/program/erase energy and time", "program/erase-only circuit area",
                              "level shifter area from upstream writeVoltage"],
    }
