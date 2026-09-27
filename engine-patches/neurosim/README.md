# NeuroSim engine patch (CTFM)

`0001-ctfm-novel-mapping-tile-partition.patch` applies to DNN_NeuroSim_V1.4 commit `ac828e6723bf077c9b1423c5c72ff6e4981e90f4`
(CC BY-NC 4.0; the patch keeps the upstream license and copyright notices, it only touches `Inference_pytorch/NeuroSIM/Chip.cpp`).

- Tile partition: with novel mapping, `ChipCalculatePerformance` handed `TileCalculatePerformance` a tile of `numRowMatrix x numColMatrix`
  (PE-size chunks, last one partial) but built the tile array with `dimension / number of tiles` rows and columns. They agree only when the
  dimension is a multiple of the PE size; otherwise `CopyPEArray` reads past the end (SIGSEGV). For one-PE tiles (`numPENM == 1`, every
  fully connected layer) the array now has the chunk dimensions used to place the tile. Behaviour is unchanged whenever the reference ran.
- Hierarchy error: after "SubArray Size is too large" the engine kept going and dereferenced empty floorplan vectors. It now exits with -1.
  The check itself is kept.

## Patch 0002 (two-plane conductance cost model, work 12)

`0002-ctfm-two-plane-conductance-cost-model.patch` (plain diff on top of 0001; `Chip.cpp`, `Param.*`, `ProcessingUnit.cpp`, `SubArray.*`,
`Tile.cpp`, `main.cpp`, new `Ctfm.h`/`Ctfm.cpp`). Every behaviour is behind a `Param` flag that is 0 in the source, so a build that does not set
the flags prints exactly what the 0001 engine printed (regression: `local_report/evidence/12/regression-0002`, byte-identical on 10 cases).

| Flag | Effect |
| --- | --- |
| `ctfmConductanceInput` | weight files hold conductances in siemens and are used as-is (one cell per weight); no re-quantisation to cell levels, no [-1, 1] rescale |
| `ctfmDifferential` | two physical planes: per layer the arguments are G+ file, G- file, input file. Each subarray-cycle evaluates both planes; per-plane blocks (word-line drivers, mux, column read/MLSA) are counted per plane, shift-add/accumulate once, everything downstream once; the slower plane sets the clock |
| `ctfmAdcOrder` | 1 = adc_then_subtract: one MLSA per plane plus a digital subtractor (engine `Adder`, ADC bits + sign, pipelined like the engine's own adder). 2 = subtract_then_adc: the signed sensing/analog subtraction has no model, so the converter is not costed |
| `ctfmNoDuplication` | no throughput-oriented weight duplication (`SubArrayDup`/`PEDesign` return 1); the reference engine duplicated the 128x10 layer into idle subarrays |
| `ctfmReadOnly` | the source-line switch matrix and write level shifters (write-only circuits) are not part of the read datapath area/leakage |
| `ctfmUsedOnly` | subarray slots of a partially filled PE that hold no weights are not built (area and leakage of the slot removed; PE-level shared blocks stay) |

With any flag set the engine also prints a ledger (`CTFM_FLAGS`, `CTFM_PARAMS`, `CTFM_SLOT`, `CTFM_LAYER`): per layer and plane the energy of each
subarray-level block, the sum of the column conductance the engine derived from the files, rows read, weight cells, used and instantiated slots.
`neurosim_alignment_check.py` compares those with numbers computed from the same files.

Apply both patches to a clean clone:

    git clone https://github.com/neurosim/DNN_NeuroSim_V1.4.git neurosim-diff
    git -C neurosim-diff checkout ac828e6723bf077c9b1423c5c72ff6e4981e90f4
    git -C neurosim-diff am ../engine-patches/neurosim/0001-ctfm-novel-mapping-tile-partition.patch
    git -C neurosim-diff apply ../engine-patches/neurosim/0002-ctfm-two-plane-conductance-cost-model.patch

The adapter decides whether patch 0002 is present by reading `ProcessingUnit.cpp` (`engine_fixes()["two_plane_cost_model"]`); without it the
`assumed_proxy` option is unavailable.

Apply to a clean clone (the reference checkout is never modified):

    git clone https://github.com/neurosim/DNN_NeuroSim_V1.4.git neurosim-fixed
    git -C neurosim-fixed checkout ac828e6723bf077c9b1423c5c72ff6e4981e90f4
    git -C neurosim-fixed am ../engine-patches/neurosim/0001-ctfm-novel-mapping-tile-partition.patch

Point `CTFM_NEUROSIM_ROOT` at the patched checkout after building it (`make -C Inference_pytorch/NeuroSIM`). The adapter reads
`Chip.cpp` to decide whether the patch is present (`engine_fixes`).

Evidence and validation: `local_report/evidence/11/`, scripts `scripts/neurosim_trace_configs.py`, `neurosim_fix_validate.py`,
`neurosim_partial_tile_bound.py`.
