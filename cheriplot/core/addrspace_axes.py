#-
# Copyright (c) 2016 Alfredo Mazzinghi
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

import numpy as np
import logging
import sys

from matplotlib import pyplot as plt
from matplotlib import transforms, axes, scale, axis, lines
from matplotlib.projections import register_projection
from matplotlib.cbook import iterable
from matplotlib.ticker import Formatter, FixedLocator, Locator

from itertools import repeat
from functools import reduce
from operator import attrgetter
from sortedcontainers import SortedDict

from cheriplot.utils import ProgressPrinter

logger = logging.getLogger(__name__)

class AddressSpaceCollapseTransform(transforms.Transform):
    """
    Transform that shrinks selected segments of the address-space

    Given a list of address ranges in which we are not interested,
    the trasform applies a linear scale to the address-space regions
    marked as Range.T_KEEP, a different scale is applied to Range.T_OMIT
    regions so that these occupy 5% of the total size of the
    Range.T_KEEP regions.
    """

    def __init__(self, *args, **kwargs):
        super(AddressSpaceCollapseTransform, self).__init__(*args, **kwargs)
        self.target_ranges = RangeSet()
        """List of ranges to keep and omit"""

        self.omit_scale = 1
        """Scale factor of the omitted address ranges"""

        self.target_ranges.append(Range(0, np.inf, Range.T_KEEP))

        self._precomputed_offsets = None
        """SortedDict ... """

        self._inverse = False
        """Is this transform performing the direct or inverse operation"""

        self.has_inverse = False # pyplot seems not to care
        self.is_separable = True
        self.input_dims = 2
        self.output_dims = 2
        self._precompute_offsets()

    def update_range(self, range_list):
        """
        Update parameters depending on the omit ranges.
        The range list must be complete, in the sense that it should
        mark every part of the address-range without holes as either
        omit or keep.
        """
        self.target_ranges = range_list

        keep = [r for r in self.target_ranges if r.rtype == Range.T_KEEP]
        omit = [r for r in self.target_ranges if r.rtype == Range.T_OMIT]
        # total size of the KEEP ranges
        keep_size = reduce(lambda acc,r: acc + r.size
                           if r.size < np.inf else acc, keep, 0)
        omit_size = reduce(lambda acc,r: acc + r.size
                           if r.size < np.inf else acc, omit, 0)
        if omit_size != 0:
            # we want the omitted ranges to take up 5% of the keep ranges
            # in size
            # scale = <percent_of_keep_size_to_take> * sum(keep) / sum(omit)
            self.omit_scale = 0.05 * keep_size / omit_size
        self._precompute_offsets()

    def _precompute_offsets(self):
        # reset previous offsets
        self._precomputed_offsets = SortedDict()
        x_collapsed = 0
        for r in self.target_ranges:
            r_scale = 1 if r.rtype == Range.T_KEEP else self.omit_scale
            self._precomputed_offsets[r.start] = (x_collapsed, r_scale)
            x_collapsed += r.size * r_scale

    def get_x(self, x_dataspace):
        """
        Scale the x from data-space coordinates to the collapsed
        address-space coordinates.
        The conversion uses a fast lookup of precomputed offsets
        based on the omit/keep range intervals.
        """
        if x_dataspace < 0:
            return x_dataspace
        base_idx = self._precomputed_offsets.bisect_left(x_dataspace)
        if (len(self._precomputed_offsets) == base_idx or
            self._precomputed_offsets.iloc[base_idx] > x_dataspace):
            key = self._precomputed_offsets.iloc[base_idx - 1]
        else:
            key = x_dataspace
        x_collapsed, x_scale = self._precomputed_offsets[key]
        return x_collapsed + (x_dataspace - key) * x_scale

    def get_x_inv(self, x):
        """
        Inverse of get_x

        Find the address range corresponding to the plot range
        given by scanning all the target ranges
        """
        x_inverse = 0
        x_current = 0
        for r in self.target_ranges:
            if r.rtype == Range.T_KEEP:
                if x > x_current + r.size:
                    x_current += r.size
                    x_inverse += r.size
                else:
                    x_inverse += x - x_current
                    break
            elif r.rtype == Range.T_OMIT:
                scaled_size = r.size * self.omit_scale
                if x > x_current + scaled_size:
                    x_current += scaled_size
                    x_inverse += r.size
                else:
                    x_inverse += (x - x_current) / self.omit_scale
                    break
            else:
                logger.error("The range %s must have a valid type", r)
                raise ValueError("Unexpected range in transform %s", r)
        return x_inverse

    def transform_x(self, x):
        """
        Handle the X axis transformation
        """
        if self._inverse:
            return self.get_x_inv(x)
        else:
            return self.get_x(x)

    def transform_non_affine(self, datain):
        """
        The transform modifies only the X-axis, Y-axis is identity

        datain is a numpy array of size Nx2
        return a numpy array of size Nx2
        """
        _prev = np.array(datain)
        dataout = np.array(datain)
        for point in dataout:
            point[0] = self.transform_x(point[0])
        return dataout

    def inverted(self):
        trans = AddressSpaceCollapseTransform()
        trans.target_ranges = self.target_ranges
        trans.omit_scale = self.omit_scale
        trans._inverse = not self._inverse
        return trans


class AddressSpaceScale(scale.ScaleBase):
    """
    Non-uniform scale that applies a different scaling function
    to parts of the address space marked as "not interesting"
    (:attr:`Range.T_OMIT`)
    """

    name = "scale_addrspace"

    max_address = 0xFFFFFFFFFFFFFFFF

    class HexFormatter(Formatter):
        def __call__(self, x, pos=None):
            return "0x%x" % int(x)


    class AddressSpaceTickLocator(Locator):
        def __init__(self, scale):
            self.scale = scale
            """The address space scale"""

        def __call__(self):
            vmin, vmax = self.axis.get_view_interval()
            return self.tick_values(vmin, vmax)

        def tick_values(self, vmin, vmax):
            """
            Return the location of the ticks using the
            scale transform to convert from data ticks to
            ticks in the scaled axis coordinates
            """
            trans = self.scale.transform
            ranges = trans.target_ranges
            trans = self.scale.get_transform()
            values = []
            for r in ranges:
                if r.rtype == Range.T_KEEP:
                    if len(values) > 0:
                        prev = trans.transform((values[-1], 0))[0]
                        curr = trans.transform((r.start, 0))[0]
                        # XXX 2**12 is an empiric value we should use
                        # the bounding box of the label but there is no
                        # easy way to get it from here
                        if curr - prev < 2**12:
                            # skip tick if they end up too close
                            continue
                    values.append(r.start)

            return values


    def __init__(self, axis, **kwargs):
        super(AddressSpaceScale, self).__init__()
        self.transform = AddressSpaceCollapseTransform()

    def get_transform(self):
        return self.transform

    def set_default_locators_and_formatters(self, axis):
        axis.set_major_locator(self.AddressSpaceTickLocator(self))
        axis.set_major_formatter(self.HexFormatter())
        axis.set_minor_formatter(self.HexFormatter())

    def limit_range_for_scale(self, vmin, vmax, minpos):
        """
        Just return the linear limit, the trasformation of the scale
        will be applied later on when setting the viewLimit on the
        axis Spine.
        """
        return max(vmin, 0), min(vmax, self.max_address)


scale.register_scale(AddressSpaceScale)


class AddressSpaceXTick(axis.XTick):

    def _get_ticklabel_line(self):
        axis_trans = self.axes.get_xaxis_transform(which="tick1")
        text_trans = self._get_text1_transform()[0]
        tick_position = axis_trans.transform((self.tick1line.get_xdata()[0],
                                              self.tick1line.get_ydata()[0]))
        label_position = text_trans.transform(self.label1.get_position())
        x = (tick_position[0], label_position[0])
        y = (tick_position[1], label_position[1])
        line = lines.Line2D(x, y, linestyle="solid", color="black")
        return line

    # @allow_rasterization
    def draw(self, renderer):
        super(AddressSpaceXTick, self).draw(renderer)

        line = self._get_ticklabel_line()
        line.draw(renderer)


class AddressSpaceXAxis(axis.XAxis):
    """
    Custom XAxis for the AddressSpace projection
    """

    def _get_tick(self, major):
        """
        Force labels to be vertical
        """
        if major:
            tick_kw = self._major_tick_kw
        else:
            tick_kw = self._minor_tick_kw
        tick = AddressSpaceXTick(self.axes, 0, '', major=major, **tick_kw)
        prop = {"rotation": "vertical"}
        tick.label1.update(prop)
        tick.label2.update(prop)
        return tick

    def _update_ticks(self, renderer):
        ticks = super(AddressSpaceXAxis, self)._update_ticks(renderer)

        # get list of bounding boxes for major and minor ticks (with labels)
        bboxes, bboxes2 = self._get_tick_bboxes(ticks, renderer)

        # iterate over each major tick and move it to avoid overlapping with
        # other ticklabels
        def _shift_ticklabel(ticks, idx, new_x):
            prev_idx = max(idx - 1, 0)
            next_idx = min(idx + 1, len(ticks) - 1)
            logger.debug("START shift_ticklabel %d %d %d", prev_idx, idx, next_idx)
            (prev_bbox, bbox, next_bbox), _ = self._get_tick_bboxes(
                (ticks[prev_idx], ticks[idx], ticks[next_idx]), renderer)
            # direction > 0 when moving to the right
            direction = new_x - bbox.x0
            logger.debug("shift direction: %d", direction >= 0)

            # shift the tick
            _xxx, y = ticks[idx].label1.get_position()
            inv = ticks[idx].label1.get_transform().inverted()
            new_loc, _ = inv.transform((new_x, 0))
            ticks[idx].label1.set_position((new_loc, y))
            logger.debug("shift tick %d: %s -> %s", idx, _xxx, new_loc)

            # get updated bbox
            (bbox,), _ = self._get_tick_bboxes([ticks[idx]], renderer)
            if idx > 0 and bbox.overlaps(prev_bbox) and direction < 0:
                new_x0 = prev_bbox.x0 - (prev_bbox.x1 - bbox.x0) / 2
                _shift_ticklabel(ticks, prev_idx, new_x0)
            if idx < len(ticks) and bbox.overlaps(next_bbox) and direction > 0:
                new_x0 = next_bbox.x0 + (bbox.x1 - next_bbox.x0) / 2
                logger.debug("overlap next")
                _shift_ticklabel(ticks, next_idx, new_x0)
            logger.debug("END shift_ticklabel %d %d %d", prev_idx, idx, next_idx)

        for idx in range(0, len(ticks) - 1):
            # for idx in range(0, 4):
            logger.debug("Ticks %d, %d", idx, idx + 1)
            (bbox, next_bbox), _ = self._get_tick_bboxes(
                [ticks[idx], ticks[idx + 1]], renderer)
            if bbox.overlaps(next_bbox):
                delta = (bbox.x1 - next_bbox.x0) / 2
                logger.debug("Bbox overlap %d: %s -> %s", idx, bbox.x0, bbox.x0 - delta)
                _shift_ticklabel(ticks, idx, bbox.x0 - delta)
                logger.debug("Bbox overlap %d: %s -> %s", idx + 1, next_bbox.x0, next_bbox.x0 + delta)
                _shift_ticklabel(ticks, idx + 1, next_bbox.x0 + delta)
        return ticks

    def _get_pixel_distance_along_axis(self, where, perturb):
        """
        Like the polar plot it is not meaningful
        """
        return 0.0


class AddressSpaceAxes(axes.Axes):
    """
    Axes class for various plots involving considerations on
    address-spaces
    """

    name = "custom_addrspace"

    DEFAULT_OMIT = 0
    """Default mode: omit all non-included addresses"""
    DEFAULT_INCLUDE = 1
    """Default mode: include all non-omitted addresses"""

    def __init__(self, *args, **kwargs):
        self.omit_filters = RangeSet()
        self.include_filters = RangeSet()
        self.mode = AddressSpaceAxes.DEFAULT_INCLUDE
        self._status_message = ""
        kwargs["xscale"] = "scale_addrspace"
        super(AddressSpaceAxes, self).__init__(*args, **kwargs)

    def _init_axis(self):
        """
        We need a custom XAxis because there is currently no way
        of setting the tick label direction to vertical from the
        Scale class
        """
        self.xaxis = AddressSpaceXAxis(self)
        self.spines['bottom'].register_axis(self.xaxis)
        self.spines['top'].register_axis(self.xaxis)
        self.yaxis = axis.YAxis(self)
        self.spines['left'].register_axis(self.yaxis)
        self.spines['right'].register_axis(self.yaxis)
        self._update_transScale()

    def _set_lim_and_transforms(self):
        """
        Override transform initialization
        """

        # axis coords to display coords
        self.transAxes = transforms.BboxTransformTo(self.bbox)

        # X and Y axis scaling
        self.transScale = transforms.TransformWrapper(
            transforms.IdentityTransform())
        # transform from given Bbox to unit Bbox
        # the given transformedBbox is updated every time the
        # viewLim changes or the transScale changes
        self.transLimits = transforms.BboxTransformFrom(
            transforms.TransformedBbox(self.viewLim, self.transScale))

        # data to display coordinates
        self.transData = self.transScale + (
            self.transLimits + self.transAxes)

        # blended transforms for xaxis and yaxis
        self._xaxis_transform = transforms.blended_transform_factory(
            self.transData, self.transAxes)
        self._yaxis_transform = transforms.blended_transform_factory(
            self.transAxes, self.transData)

    def _filter(self, target_list, other_list, target_range):
        """
        Generic omit or include

        XXX:
        - rename to a more meaningful name
        - only take the omit range list, the other list is never used
        """
        if len(other_list.match_overlap_range(target_range)):
            raise ValueError("Range %s is present in another filter" %
                             target_range)

        existing_range = target_list.match_overlap_range(target_range)
        assert len(existing_range) < 2, "Too many overlapping ranges %s, %s" % (
            existing_range, target_range)
        try:
            target_range = existing_range[0] + target_range
        except IndexError:
            pass
        finally:
            target_list.append(target_range)

    def _map_omit(self, map_range):
        """
        Map the omit and include lists on the given range.
        The range is split in omit regions and include regions,
        the omit regions are the ones to be shrunk in the plot
        while the include regions are rendered normally.

        Return a RangeSet containing the ranges to keep and omit that overlap
        the input range
        """
        if self.mode == AddressSpaceAxes.DEFAULT_INCLUDE:
            logger.debug("Map omit regions on %s", map_range)
            regions = self.omit_filters.match_overlap_range(map_range)
            # type of mapped regions
            rtype = Range.T_OMIT
            # type of complement regions
            c_rtype = Range.T_KEEP
        else:
            logger.debug("Map include regions on %s", map_range)
            regions = self.include_filters.match_overlap_range(map_range)
            # type of mapped regions
            rtype = Range.T_KEEP
            # type of complement regions
            c_rtype = Range.T_OMIT

        regions.sort(key=attrgetter("start"))
        logger.debug("Found %d regions for %s: %s", len(regions), map_range, regions)
        mapped = []
        complement = []
        start = None
        for r in regions:
            # r.start can not be after target.end so the
            # mapped range start always in the target boundaries
            # same applies for the r.end and target.end
            start = max(map_range.start, r.start)
            end = min(map_range.end, r.end)
            m_range = Range(start, end, rtype)
            # logger.debug("m_range %s", m_range)
            # regions are assumed to be sorted by start address
            c_start = mapped[-1].end if len(mapped) else map_range.start
            c_end = start
            c_range = Range(c_start, c_end, c_rtype)
            # logger.debug("c_range %s", c_range)
            if m_range.size > 0:
                mapped.append(m_range)
            if c_range.size > 0:
                complement.append(c_range)
        # add last block to complement if necessary
        c_start = mapped[-1].end if len(mapped) else map_range.start
        c_end = map_range.end
        c_range = Range(c_start, c_end, c_rtype)
        if c_range.size > 0:
            complement.append(c_range)

        logger.debug("Mapped: %s", mapped)
        logger.debug("Complement: %s", complement)

        ranges = RangeSet(mapped + complement)
        # XXX may keep the lists separated to avoid the need to sort
        ranges.sort(key=attrgetter("start"))
        return ranges

    def set_omit_ranges(self, ranges):
        """
        Configure the set of addresses (x-axis values) that
        are omitted from the plot. These are collapsed to
        a small separation space between chunks of address-space
        that are displayed normally.

        Accept an Nx2 array in the form [[r_start, r_end], ...]
        """
        for r in ranges:
            self._filter(self.omit_filters, self.include_filters,
                         Range(r[0], r[1], Range.T_OMIT))
        all_ranges = self._map_omit(Range(0, np.inf))
        self.xaxis.get_transform().update_range(all_ranges)

    def set_status_message(self, message):
        """
        Set the status message to show in the status bar along with
        the (x,y) coordinates of the mouse
        """
        self._status_message = message

    def format_coord(self, x, y):
        """
        Add the status message to the status bar format string
        """
        xy_fmt = super(AddressSpaceAxes, self).format_coord(x, y)
        return "%s %s" % (xy_fmt, self._status_message)


register_projection(AddressSpaceAxes)

class Range:

    T_OMIT = 0
    T_KEEP = 1
    T_UNKN = -1

    def __init__(self, start, end, rtype=-1):
        # make sure that start <= end always
        self.start = min(start, end)
        self.end = max(start, end)
        self.rtype = rtype
        """The type is used to distinguish omit and keep ranges"""

    @property
    def size(self):
        return self.end - self.start

    def __str__(self):
        return "<Range [%x, %x]>" % (self.start, self.end)

    def __repr__(self):
        return str(self)

    def __add__(self, other):
        return Range(min(self.start, other.start), max(self.end, other.end))

    def __iter__(self):
        yield self.start
        yield self.end

    def __contains__(self, target):
        """
        target can be a Range or a single address
        """
        try:
            return self.start <= target.end and target.start < self.end
        except:
            return self.start <= target and target < self.end

    def __str__(self):
        start = "0x%x" if type(self.start) == int else "%s"
        end = "0x%x" if type(self.end) == int else "%s"
        if self.rtype == self.T_OMIT:
            rtype = "OMIT"
        elif self.rtype == self.T_KEEP:
            rtype = "KEEP"
        else:
            rtype = "UNK"
        fmt = "<Range s:" + start + " e:" + end + " t:%s>"
        return fmt % (self.start, self.end, rtype)

    def __hash__(self):
        return hash(self.start) ^ hash(self.end) ^ hash(self.rtype)


class RangeSet(list):
    """
    Represent a list ranges that can be searched for overlaps
    """

    def __init__(self, *args):
        super(RangeSet, self).__init__(*args)

    def match_overlap(self, addr):
        """
        Return the list of ranges containing addr
        """
        range_ = Range(addr, addr)
        return self.match_overlap_range(ranges, range_)

    def match_overlap_range(self, target):
        """
        Return the list of ranges overlapping target
        XXX ranges are considered to be open, no overlapping
        occurs if the ranges are contiguous.
        """
        overlaps = [r for r in self if (r.start < target.end and
                                        r.end > target.start)]
        return RangeSet(overlaps)

    def first_overlap_range(self, target):
        """
        Return the first range in the set that overlaps target
        """
        for r in self:
            if (r.start < target.end and r.end > target.start):
                return r
        return None

    def pop_overlap_range(self, target):
        """
        Return the index of the first range in the set 
        that overlaps target
        """
        for i,r in enumerate(self):
            if (r.start < target.end and r.end > target.start):
                return self.pop(i)
        return None
