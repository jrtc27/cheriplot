#!/usr/bin/python

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

"""
This script plots the out-of-bound pointer manipulations.
"""

import argparse as ap
import sys
import logging
import cProfile
import pstats

from cheriplot.plot.provenance import MultiPointerSizeCdfPlot
from cheriplot.core.tool import PlotTool

logger = logging.getLogger(__name__)

class CdfPlotTool(PlotTool):

    def init_arguments(self):
        super(CdfPlotTool, self).init_arguments()
        self.parser.add_argument("additional_traces",
                                 help="Additional trace files to parse",
                                 nargs="*")

    def _run(self, args):
        traces = args.additional_traces + [args.trace]
        plot = MultiPointerSizeCdfPlot(traces, args.cache)

        if args.outfile:
            plot.save(args.outfile)
        else:
            plot.show()

def main():
    tool = CdfPlotTool()
    tool.run()

if __name__ == "__main__":
    main()
