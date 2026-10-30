"""
manual_selection.py — validation shared by the two manual-flag paths
(ms_flag_data on an MS, ms_flag_caltable mode='manual' on a caltable).

flagdata(mode='manual') with every selection empty flags the whole target: each
selection defaults to "all" and the task has no guard of its own. So both tools
require at least one non-empty selection and a reason. CASA-free.
"""

from __future__ import annotations


def validate_manual_selection(
    selection: dict[str, str], reason: str, allowed: tuple[str, ...], target: str
) -> dict[str, str]:
    """Return the non-empty, stripped selection entries; raise on an unusable call.

    Args:
        selection: flagdata selection keyword → value.
        reason:    Why the data is flagged; required.
        allowed:   Selection keys flagdata supports on this target.
        target:    'Measurement Set' or 'caltable', for the error text.
    """
    from ms_inspect.exceptions import ComputationError

    unknown = set(selection) - set(allowed)
    if unknown:
        raise ComputationError(
            f"Unsupported {target} selection {sorted(unknown)}; flagdata supports "
            f"only {list(allowed)} here.",
            ms_path="",
        )
    given = {k: v.strip() for k, v in selection.items() if v and v.strip()}
    if not given:
        raise ComputationError(
            f"Manual flagging needs at least one of {list(allowed)}: "
            f"flagdata(mode='manual') with an empty selection flags the entire {target}.",
            ms_path="",
        )
    if not reason or not reason.strip():
        raise ComputationError(
            "Manual flagging needs a reason (the measurement that justified the flag).",
            ms_path="",
        )
    return given
