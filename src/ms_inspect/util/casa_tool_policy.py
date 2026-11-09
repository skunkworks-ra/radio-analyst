"""
casa_tool_policy.py — which casatools methods ms_casa_tool may call, and when.

CASA-free. The casatools API has no machine-readable read/write marking, so the
tiers below are written by hand from the method list and docstrings of the
installed casatools (dir(casatools.table())). They are INFERRED, and a unit
test checks that every public method of the installed class sits in exactly one
tier, so a casatools upgrade that adds a method fails loudly instead of being
silently allowed or silently refused.

Tiers:
  READ   always allowed. `open` is forced to nomodify=True.
  COPY   allow_write=True. Makes a NEW table or file inside the workdir. The
         destination must not exist. A table made here is recorded in the
         workdir's copy manifest: that is what makes it a "copy".
  EDIT   allow_write=True. Changes a table, and only a table in the manifest
         that was opened with nomodify=False. The source MS is never in the
         manifest, so it can never be edited through this tool.
  NEVER  refused in every mode.
"""

from __future__ import annotations

from dataclasses import dataclass

READ, COPY, EDIT, NEVER = "read", "copy", "edit", "never"


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    read: frozenset[str]
    copy: frozenset[str]
    edit: frozenset[str]
    never: frozenset[str]

    def tier(self, method: str) -> str | None:
        """Tier of a method, or None when the policy does not list it."""
        for label, names in (
            (READ, self.read),
            (COPY, self.copy),
            (EDIT, self.edit),
            (NEVER, self.never),
        ):
            if method in names:
                return label
        return None

    def all_methods(self) -> frozenset[str]:
        return self.read | self.copy | self.edit | self.never


_TABLE = ToolPolicy(
    name="table",
    read=frozenset(
        {
            # lifecycle (open is forced to nomodify=True; `done` is a synonym of close)
            "open",
            "close",
            "done",
            # shape and names
            "name",
            "nrows",
            "ncols",
            "colnames",
            "keywordnames",
            "fieldnames",
            "colkeywordnames",
            "colfieldnames",
            # cell and column reads
            "getcell",
            "getcellslice",
            "getcol",
            "getcolslice",
            "getvarcol",
            "getcolshapestring",
            "iscelldefined",
            "isscalarcol",
            "isvarcol",
            # keywords
            "getkeyword",
            "getkeywords",
            "getcolkeyword",
            "getcolkeywords",
            # descriptions and metadata
            "getdesc",
            "getcoldesc",
            "getdminfo",
            "info",
            "colarraytype",
            "coldatatype",
            "endianformat",
            "ok",
            # computation on a column
            "statistics",
            "calc",
            # state queries (lock debugging)
            "isopened",
            "iswritable",
            "haslock",
            "lockoptions",
            "ismultiused",
            "datachanged",
            "listlocks",
        }
    ),
    copy=frozenset({"copy", "create", "fromascii", "fromfits", "toasciifmt"}),
    edit=frozenset(
        {
            "putcell",
            "putcellslice",
            "putcol",
            "putcolslice",
            "putvarcol",
            "putkeyword",
            "putkeywords",
            "putcolkeyword",
            "putcolkeywords",
            "putinfo",
            "addcols",
            "addrows",
            "addreadmeline",
            "copyrows",
            "removecols",
            "removerows",
            "removekeyword",
            "removecolkeyword",
            "renamecol",
            "flush",
        }
    ),
    never=frozenset(
        {
            "taql",  # full TaQL: UPDATE / INSERT / DELETE
            "query",  # makes a reference table; with a name, writes it to disk
            "selectrows",  # reference table
            "row",  # accessor object, not JSON
            "getcoliter",  # iterator object, not JSON
            "createmultitable",
            "fromASDM",
            "lock",
            "unlock",
            "resync",
            "clearlocks",
            "browse",  # GUI
            "summary",  # goes to the logger, returns nothing
            "setmaxcachesize",
            "showcache",
            "rownumbers",  # input parameters ignored
            "testincrstman",
        }
    ),
)

#: casatools classes ms_casa_tool serves. Only `table` in v1.
POLICIES: dict[str, ToolPolicy] = {"table": _TABLE}

#: Parameter names that carry a destination path, per COPY method: (table, file).
COPY_DEST_PARAMS: dict[str, tuple[str, ...]] = {
    "copy": ("newtablename",),
    "create": ("tablename",),
    "fromascii": ("tablename",),
    "fromfits": ("tablename",),
    "toasciifmt": ("asciifile", "headerfile"),
}

#: COPY methods whose destination is a table (recorded in the manifest).
COPY_MAKES_TABLE = frozenset({"copy", "create", "fromascii", "fromfits"})

#: COPY methods that read an input file by this parameter.
COPY_INPUT_FILES: dict[str, tuple[str, ...]] = {
    "fromascii": ("asciifile", "headerfile"),
    "fromfits": ("fitsfile",),
}

#: COPY methods that create the session table (they replace the open one).
COPY_OPENS_TABLE = frozenset({"create", "fromascii", "fromfits"})
