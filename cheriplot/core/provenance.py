#-
# Copyright (c) 2016-2017 Alfredo Mazzinghi
# All rights reserved.
#
# This software was developed by SRI International and the University of
# Cambridge Computer Laboratory under DARPA/AFRL contract FA8750-10-C-0237
# ("CTSRD"), as part of the DARPA CRASH research programme.
#
# @BERI_LICENSE_HEADER_START@
#
# Licensed to BERI Open Systems C.I.C. (BERI) under one or more contributor
# license agreements.  See the NOTICE file distributed with this work for
# additional information regarding copyright ownership.  BERI licenses this
# file to you under the BERI Hardware-Software License, Version 1.0 (the
# "License"); you may not use this file except in compliance with the
# License.  You may obtain a copy of the License at:
#
#   http://www.beri-open-systems.org/legal/license-1-0.txt
#
# Unless required by applicable law or agreed to in writing, Work distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations under the License.
#
# @BERI_LICENSE_HEADER_END@
#

"""
Provenance graph implementation and helper classes.
"""

from enum import IntEnum
from cached_property import cached_property
from functools import partialmethod
from graph_tool.all import *

class CheriCapPerm(IntEnum):
    """
    Enumeration of bitmask for the capability permission bits.
    """

    GLOBAL = 1
    EXEC = 1 << 1
    LOAD = 1 << 2
    STORE = 1 << 3
    CAP_LOAD = 1 << 4
    CAP_STORE = 1 << 5
    CAP_STORE_LOCAL = 1 << 6
    SEAL = 1 << 7
    # XXXAM qemu currently uses 8, spec says 10
    SYSTEM_REGISTERS = 1 << 10 | 1 << 8


class CheriNodeOrigin(IntEnum):
    """
    Enumeration of the possible originators of
    nodes in the provenance graph.
    """

    UNKNOWN = -1
    ROOT = 0
    # instructions
    SETBOUNDS = 1
    FROMPTR = 2
    ANDPERM = 3
    # aggregate nodes
    PTR_SETBOUNDS = 4
    # system calls
    # the start and end are flags
    SYS_MMAP = 5
    SYS_MUNMAP = 6


class CheriCap:
    """
    Hold the data of a CHERI capability.
    """

    MAX_ADDR = 0xffffffffffffffff
    MAX_OTYPE = 0x00ffffff

    def __init__(self, pct_cap=None):
        """
        Initialize CHERI capability data.

        :param pct_cap: pycheritrace capability
        :type pct_cap: :class:`pycheritrace.capability_register`
        """
        self.base = pct_cap.base if pct_cap else None
        """Capability base."""

        self.length = pct_cap.length if pct_cap else None
        """Capability length."""

        self.offset = pct_cap.offset if pct_cap else None
        """Capability offset."""

        self.permissions = pct_cap.permissions if pct_cap else None
        """Capability permissions bitmap."""

        self.objtype = pct_cap.type & self.MAX_OTYPE if pct_cap else None
        """Capability object type."""

        self.valid = pct_cap.valid if pct_cap else False
        """Is the capability valid?"""

        # XXX the unsealed property actually contains the sealed bit
        # the naming is confusing and should be changed.
        self.sealed = pct_cap.unsealed if pct_cap else False
        """Is the capability sealed?"""

        self.t_alloc = -1
        """Allocation time"""

        self.t_free = -1
        """Free time"""

    @property
    def bound(self):
        """Convenience property to get base + length."""
        if (self.base is not None and self.length is not None):
            return (self.base + self.length) % self.MAX_ADDR
        return None

    def __str__(self):
        """Get string representation of the capability."""
        base = "%x" % self.base if self.base is not None else "-"
        leng = "%x" % self.length if self.length is not None else "-"
        off = "%x" % self.offset if self.offset is not None else "-"
        perms = self.str_perm()
        objtype = "%x" % self.objtype if self.objtype is not None else "-"
        return "[b:%s o:%s l:%s p:(%s) t:%s v:%s s:%s] t_alloc:%d t_free:%d" % (
            base, off, leng, perms, objtype, self.valid, self.sealed,
            self.t_alloc, self.t_free)

    def has_perm(self, perm):
        """
        Check whether the node has the given permission bit set

        :param perm: permission bit
        :type perm: :class:`.CheriCapPerm`
        :return: True or False
        :rtype: bool
        """
        if self.permissions & perm:
            return True
        return False

    def str_perm(self):
        """
        Convert permission bitmask to human readable list of flags

        :return: string containing the names of the set permission bits
        :rtype: string
        """
        perm_string = ""
        if self.permissions:
            for perm in CheriCapPerm:
                if self.permissions & perm.value:
                    if perm_string:
                        perm_string += " "
                    perm_string += perm.name
        if not perm_string:
            perm_string = "None"
        return perm_string

    def __eq__(self, other):
        """
        Override equality test to have a shorthand way to 
        compare capability equality.
        """
        return (self.base == other.base and
                self.length == other.length and
                self.offset == other.offset and
                self.permissions == other.permissions and
                self.objtype == other.objtype and
                self.valid == other.valid and
                self.sealed == other.sealed and
                self.t_alloc == other.t_alloc and
                self.t_free == other.t_free)

    def __ne__(self, other):
        return not self == other


class NodeData:
    """
    All the data associated with a node in the capability
    graph.
    """

    class DerefType(IntEnum):
        """Types of capability dereference."""
        DEREF_LOAD = 1
        DEREF_STORE = 2
        DEREF_CALL = 3

    @classmethod
    def from_operand(cls, op):
        """
        Create data from a :class:`cheriplot.core.parser.Operand`
        """
        data = cls()
        if not op.is_register or not op.is_capability:
            logger.error("Attempt to create provenance node from "
                         "non-capability operand %s", op)
            raise ValueError("Operand is not a capability")
        data.cap = CheriCap(op.value)
        data.cap.t_alloc = op.instr.entry.cycles
        data.pc = op.instr.entry.pc
        data.is_kernel = op.instr.entry.is_kernel()
        return data

    def __init__(self):
        self.address = {}
        """
        Map the time when the capability is stored in memory to
        the address where it is stored location.
        """

        self.deref = {"time": [], "addr": [], "is_cap": [], "type": []}
        """
        Store dereferences of a capability, in a table-like structure,
        the type is defined in :class:`NodeData.DerefType`
        """

        self.cap = None
        """Cheri capability data, see :class:`.CheriCap`."""

        self.origin = CheriNodeOrigin.UNKNOWN
        """What produced this node."""

        self.pc = None
        """The PC of the instruction that produced this node."""

        self.is_kernel = False
        """Is this node coming from a trace entry executed in kernel space?"""

    def add_deref(self, time, addr, cap, type_):
        """Append a dereference to the dereference table."""
        self.deref["time"].append(time)
        self.deref["addr"].append(addr)
        self.deref["is_cap"].append(cap)
        self.deref["type"].append(type_)

    # shortcuts for add_deref
    add_load = partialmethod(add_deref, type_=DerefType.DEREF_LOAD)
    add_store = partialmethod(add_deref, type_=DerefType.DEREF_STORE)
    add_call = partialmethod(add_deref, type_=DerefType.DEREF_CALL)

    def __str__(self):
        return "%s origin:%s pc:0x%x (kernel %d)" % (
            self.cap, self.origin.name, self.pc or 0, self.is_kernel)
