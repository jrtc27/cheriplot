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

import logging
import sys

from datetime import datetime

logger = logging.getLogger(__name__)

class ProgressPrinter:
    """
    Print progress information based on the log-level
    """

    def __init__(self, end, desc="Progress", start=0, step=1,
                 level=logging.INFO):
        self.start = start
        """Start value of progress counter"""

        self.end = end
        """End value of progress counter"""

        self.desc = desc
        """Counter description"""

        self.progress = 0
        """Current % progress"""

        self.curr = 0
        """Current counter value"""

        self.step = step
        """Counter increment step"""

        self.level = level
        """Log level"""

    def advance(self, step=1, to=None):
        if logger.getEffectiveLevel() > self.level:
            return
        if to is not None:
            self.curr = to
        else:
            self.curr += step
        progress = int(self.curr * 100 / (self.end - self.start))
        if (progress != self.progress):
            self.progress = progress
            sys.stdout.write("\r%s [%d%%]" % (self.desc, progress))
            sys.stdout.flush()
            
    def finish(self):
        """
        Add newline to separate upcoming output
        """
        if logger.getEffectiveLevel() < self.level:
            return
        print("\n")


class ProgressTimer:
    """
    Context manager that wraps a statement and measures the run time.
    The message can be customised to show different information along
    with the timing.
    """

    def __init__(self, msg="", logger_inst=None):
        self.msg = msg
        self.logger = logger_inst or logger
        self.start = None

    def __enter__(self):
        self.start = datetime.now()
        self.logger.info("%s started at %s", self.msg,
                         self.start.isoformat())

    def __exit__(self, type, value, traceback):
        end = datetime.now()
        self.logger.info("%s done at %s (time %s)", self.msg,
                         end.isoformat(), end - self.start)
