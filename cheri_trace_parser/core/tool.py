"""
Copyright 2016 Alfredo Mazzinghi

Copyright and related rights are licensed under the BERI Hardware-Software
License, Version 1.0 (the "License"); you may not use this file except
in compliance with the License.  You may obtain a copy of the License at:

http://www.beri-open-systems.org/legal/license-1-0.txt

Unless required by applicable law or agreed to in writing, software,
hardware and materials distributed under this License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
express or implied.  See the License for the specific language governing
permissions and limitations under the License.
"""

import sys
import logging
import argparse as ap
import cProfile
import pstats

class Tool:
    """
    Base class for tools that parse traces
    """

    description = ""

    def __init__(self):
        self.parser = ap.ArgumentParser(description=self.description)
        self.init_arguments()

    def init_arguments(self):
        """
        Set the command line arguments for the tool.

        This adds some default arguments for verbose logging, 
        profiling and the trace file path.
        """
        self.parser.add_argument("trace", help="Path to trace file")
        self.parser.add_argument("-v", "--verbose", help="Show debug output",
                            action="store_true")
        self.parser.add_argument("--log", help="Set logfile path")
        self.parser.add_argument("--profile",
                            help="Run in profiler (disable verbose output)",
                            action="store_true")

    def run(self):
        """
        Tool entry point, this should be called from the python main
        script.
        """
        args = self.parser.parse_args()

        # disable verbose logging when profiling
        if args.profile:
            args.verbose = False

        # setup logging
        logging_args = {}
        if args.verbose:
            logging_args["level"] = logging.DEBUG
        else:
            logging_args["level"] = logging.INFO

        if args.log:
            logging_args["filename"] = args.log

        logging.basicConfig(**logging_args)

        try:
            if args.profile:
                cProfile.runcall(self._run, (args,), {},
                                 self._get_profiler_file())
            else:
                self._run(args)
        finally:
            # print profiling results
            if args.profile:
                p = pstats.Stats(self._get_profiler_file())
                p.strip_dirs()
                p.sort_stats("cumulative")
                p.print_stats()

    def _get_profiler_file(self):
        tool_name, _ = os.path.splitext(sys.argv[0])
        return "%s.cprof" % tool_name

    def _run(self, args):
        """
        Run the tool body.

        :param args: the arguments namespace
        :type args: :class:`argparse.Namespace`
        """
        raise NotImplementedError("Missing tool body in Tool._run")


class PlotTool(Tool):

    def init_arguments(self):
        super(PlotTool, self).init_arguments()
        self.parser.add_argument("-c", "--cache",
                                 help="Enable caching of the parsed trace",
                                 action="store_true")
        self.parser.add_argument("-o", "--outfile", help="Save plot to file")
        
