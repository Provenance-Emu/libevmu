// LibEVMUShim.h — the ONLY C glue Swift needs for libevmu.
//
// libevmu's public API is 99% Swift-callable directly (device create, typed
// peripheral pointers dev->pLcd/pGamepad, EvmuLcd_pixel, EvmuFat_format,
// EvmuFileManager_load, and even the gamepad bitfields dev->pGamepad->a). The
// ONE gap is the interface cast: `EvmuIBehavior_reset/update` take an
// EvmuIBehavior* obtained via the `EVMU_IBEHAVIOR(dev)` macro — a function-like
// C macro that Swift cannot call. These inline wrappers expose exactly that as
// plain C functions. Keep this the whole shim; do not accrete convenience here.
#ifndef LIBEVMU_SHIM_H
#define LIBEVMU_SHIM_H

#include <stdbool.h>
#include <evmu/hw/evmu_device.h>
#include <evmu/types/evmu_ibehavior.h>
#include <gimbal/core/gimbal_result.h>

//! True only for a HARD error. gimbal returns non-zero "partial"/warning codes
//! on success paths (e.g. EvmuFat_format), so an EVMU_RESULT must be tested with
//! the error predicate, not `== success`. GBL_RESULT_ERROR is a function-like
//! macro, so Swift needs this wrapper.
static inline bool LibEVMU_failed(EVMU_RESULT result) {
    return GBL_RESULT_ERROR(result);
}

//! Reset the whole device (CPU, peripherals) — Swift-callable EVMU_IBEHAVIOR cast.
static inline EVMU_RESULT LibEVMU_reset(EvmuDevice* pDevice) {
    return EvmuIBehavior_reset(EVMU_IBEHAVIOR(pDevice));
}

//! Advance emulation by `ticks` milliseconds — Swift-callable EVMU_IBEHAVIOR cast.
static inline EVMU_RESULT LibEVMU_update(EvmuDevice* pDevice, EvmuTicks ticks) {
    return EvmuIBehavior_update(EVMU_IBEHAVIOR(pDevice), ticks);
}

#endif // LIBEVMU_SHIM_H
