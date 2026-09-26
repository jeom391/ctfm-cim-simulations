# NeuroSim engine patch (CTFM)

`0001-ctfm-novel-mapping-tile-partition.patch` applies to DNN_NeuroSim_V1.4 commit `ac828e6723bf077c9b1423c5c72ff6e4981e90f4`
(CC BY-NC 4.0; the patch keeps the upstream license and copyright notices, it only touches `Inference_pytorch/NeuroSIM/Chip.cpp`).

- Tile partition: with novel mapping, `ChipCalculatePerformance` handed `TileCalculatePerformance` a tile of `numRowMatrix x numColMatrix`
  (PE-size chunks, last one partial) but built the tile array with `dimension / number of tiles` rows and columns. They agree only when the
  dimension is a multiple of the PE size; otherwise `CopyPEArray` reads past the end (SIGSEGV). For one-PE tiles (`numPENM == 1`, every
  fully connected layer) the array now has the chunk dimensions used to place the tile. Behaviour is unchanged whenever the reference ran.
- Hierarchy error: after "SubArray Size is too large" the engine kept going and dereferenced empty floorplan vectors. It now exits with -1.
  The check itself is kept.

Apply to a clean clone (the reference checkout is never modified):

    git clone https://github.com/neurosim/DNN_NeuroSim_V1.4.git neurosim-fixed
    git -C neurosim-fixed checkout ac828e6723bf077c9b1423c5c72ff6e4981e90f4
    git -C neurosim-fixed am ../engine-patches/neurosim/0001-ctfm-novel-mapping-tile-partition.patch

Point `CTFM_NEUROSIM_ROOT` at the patched checkout after building it (`make -C Inference_pytorch/NeuroSIM`). The adapter reads
`Chip.cpp` to decide whether the patch is present (`engine_fixes`).

Evidence and validation: `local_report/evidence/11/`, scripts `scripts/neurosim_trace_configs.py`, `neurosim_fix_validate.py`,
`neurosim_partial_tile_bound.py`.
