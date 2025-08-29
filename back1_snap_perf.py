#!/usr/bin/env python

from __future__ import print_function

import argparse
import logging
import os
import re
import subprocess
import sys
from datetime import datetime

# Import the hotspot extractor
try:
    from snap_perf_hotspot_extractor import PerfHotspotExtractor, PerfDataMonitor
except ImportError:
    # Fallback if the module is not available
    PerfHotspotExtractor = None
    PerfDataMonitor = None
    logging.warning("Hotspot extraction module not available")

class SnapPerfError(Exception):
    pass

class ScheduleFileParser:
    def __init__(self, schedule_file, filter_suite=None, filter_tags=None, filter_flag=None, override_flag=False, override_tag=None):
        self.schedule_file = schedule_file
        self.filter_suite = filter_suite
        self.filter_tags = filter_tags if filter_tags else []
        self.filter_flag = filter_flag
        self.override_flag = override_flag  # Flag to indicate if flag is overridden by user
        self.override_tag = override_tag    # New tag to append when tag is overridden
        self.sections = []
        self.filtered_sections = []
        self.parse_schedule_file()
    
    def parse_schedule_file(self):
        if not os.path.exists(self.schedule_file):
            raise SnapPerfError(f"Schedule file not found: {self.schedule_file}")
        
        with open(self.schedule_file, 'r') as f:
            content = f.read()
        
        current_section = None
        current_params = {}
        
        for line in content.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            if line.startswith('[') and line.endswith(']'):
                if current_section:
                    section_data = {
                        'header': current_section,
                        'params': current_params.copy()
                    }
                    self.sections.append(section_data)
                        
                current_section = line
                current_params = {}
            elif ':' in line and current_section:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                current_params[key] = value
        
        if current_section:
            section_data = {
                'header': current_section,
                'params': current_params.copy()
            }
            self.sections.append(section_data)
        
        # Apply multi-step filtering: suite -> tags/flags
        self._apply_filtering()
    
    def _apply_filtering(self):
        """Apply multi-step filtering: first by suite, then by tags/flags, then apply overrides"""
        # Step 1: Filter by suite name if specified
        suite_filtered_sections = []
        if self.filter_suite:
            for section in self.sections:
                section_suite = section['params'].get('suite', '').strip()
                if section_suite == self.filter_suite:
                    suite_filtered_sections.append(section)
        else:
            suite_filtered_sections = self.sections[:]
        
        # Step 2: Apply tag/flag filtering first
        tag_flag_filtered_sections = []
        if self.filter_tags:
            # For multiple tags, collect ALL matching sections for each tag
            for tag in self.filter_tags:
                for section in suite_filtered_sections:
                    section_tag = section['params'].get('tag', '').strip()
                    if section_tag == tag or tag == '*':
                        tag_flag_filtered_sections.append(section)
        elif self.filter_flag:
            # For flag filtering, check if the flag matches any field using regex
            for section in suite_filtered_sections:
                section_flag = section['params'].get('f', '').strip()
                if self.filter_flag == '*' or re.search(self.filter_flag, section_flag, re.IGNORECASE):
                    tag_flag_filtered_sections.append(section)
        else:
            # No tag/flag filter, use all suite-filtered sections
            tag_flag_filtered_sections = suite_filtered_sections[:]
        
        # Step 3: Apply overrides to the filtered results
        if self.override_flag and not self.override_tag:
            # If ONLY flag is overridden, treat all configs as equivalent - pick only one
            # and override tag to "cpu"
            if tag_flag_filtered_sections:
                selected_section = tag_flag_filtered_sections[0].copy()
                selected_section['params'] = selected_section['params'].copy()
                selected_section['params']['tag'] = 'cpu'  # Override tag to "cpu"
                self.filtered_sections = [selected_section]
            else:
                self.filtered_sections = []
        elif self.override_flag and self.override_tag:
            # If BOTH flag and tag are overridden, all configs become functionally identical
            # Treat as equivalent - pick only one and use the overridden tag directly
            if tag_flag_filtered_sections:
                selected_section = tag_flag_filtered_sections[0].copy()
                selected_section['params'] = selected_section['params'].copy()
                selected_section['params']['tag'] = self.override_tag  # Use overridden tag directly
                self.filtered_sections = [selected_section]
            else:
                self.filtered_sections = []
        elif self.override_tag:
            # If ONLY tag is overridden, update all filtered config tags to format: Existing-tag_New-tag
            for section in tag_flag_filtered_sections:
                modified_section = section.copy()
                modified_section['params'] = modified_section['params'].copy()
                existing_tag = modified_section['params'].get('tag', '').strip()
                if existing_tag:
                    modified_section['params']['tag'] = f"{existing_tag}_{self.override_tag}"
                else:
                    modified_section['params']['tag'] = self.override_tag
                self.filtered_sections.append(modified_section)
        else:
            # No overrides, use the tag/flag filtered sections
            self.filtered_sections = tag_flag_filtered_sections[:]
    
    def get_filtered_sections(self):
        """Get sections matching the filter tag, or all sections if no filter"""
        return self.filtered_sections
    
    def get_default_values(self):
        """Get default values from the first filtered section"""
        if not self.filtered_sections:
            suite_part = f" for suite '{self.filter_suite}'" if self.filter_suite else ""
            if self.filter_tags:
                raise SnapPerfError(f"No job config found with tags '{self.filter_tags}'{suite_part} in schedule file {self.schedule_file}")
            elif self.filter_flag:
                raise SnapPerfError(f"No job config found with flag '{self.filter_flag}'{suite_part} in schedule file {self.schedule_file}")
            else:
                raise SnapPerfError(f"No job config found{suite_part} in schedule file {self.schedule_file}")
            return {}
        
        first_section = self.filtered_sections[0]
        return first_section['params']
    
    def get_matching_configs_count(self):
        """Get the number of job configs matching the filter tag"""
        return len(self.filtered_sections)

class SnapPerf:
    SUPPORTED_SUITES = [
        'TSVC_2_Single_Kernel_Binary',
        'Snappy',
        'CoreMark', 
        'Folly',
        'RAJAPerf_Base_Seq'
    ]
    
    SUPPORTED_UTILITIES = ['perf']
    
    def __init__(self):
        self.args = None
        self.schedule_parser = None
        self.output_file = None
        self._dir_number = None  # Cache the directory number
        self.generated_perf_files = []  # Track generated perf data files
        
    def parse_args(self):
        parser = argparse.ArgumentParser(
            prog='proj/ta/bin/snap_perf',
            description='A command-line interface to simplify and automate the generation of performance profile data for different builds, benchmarks, and test names. snap_perf takes in all required details (compiler, versions, suite, test, ta for schedule file, user, and tags) directly from the command line. The tool checks that all these arguments are provided, then combines them with extra information from the existing schedule file. It lets users customize or override any settings from the schedule file using the command line, ensuring each run matches exactly what\'s needed. Finally, snap_perf creates a new schedule file with all the inputs and automatically starts the process by calling the runta interface.',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog='''
utility options:
  perf                  Use Linux perf profiling utility

examples:
  proj/ta/bin/snap_perf -compiler grco-gcc -versions upstream-main/latest -suite TSVC_2_Single_Kernel_Binary -test matmul -ta grco-gcc-perf.cfg -user grco -tags CPU_LTO_O3
  proj/ta/bin/snap_perf -compiler /path/to/custom/gcc-13 -versions v1.2.3 v2.0.0 -suite CoreMark -test test1 test2 -ta grco-gcc-perf.cfg -user admin -f "o3" --save-log
  proj/ta/bin/snap_perf -compiler clang-15 -versions v2.0.0 -suite RAJAPerf_Base_Seq -test reduce scan -ta grco-llvm-perf.cfg -user admin -tags CPU_VLA GPU_CUDA -dryrun
  proj/ta/bin/snap_perf -compiler grco-gcc -versions v1.0.0 -suite TSVC_2_Single_Kernel_Binary -test matmul -ta grco-gcc-perf.cfg -user grco
  proj/ta/bin/snap_perf -compiler grco-gcc -versions v1.0.0 -suite TSVC_2_Single_Kernel_Binary -test matmul -ta grco-gcc-perf.cfg -user grco -override-flag
  proj/ta/bin/snap_perf -compiler grco-gcc -versions v1.0.0 -suite TSVC_2_Single_Kernel_Binary -test matmul -ta grco-gcc-perf.cfg -user grco -override-tag "custom"
  proj/ta/bin/snap_perf -compiler grco-gcc -versions v1.0.0 -suite TSVC_2_Single_Kernel_Binary -test matmul -ta grco-gcc-perf.cfg -user grco -override "tag=Run1 f=-O3"
  proj/ta/bin/snap_perf -compiler grco-gcc -versions v1.0.0 -suite TSVC_2_Single_Kernel_Binary -test matmul -ta grco-gcc-perf.cfg -user grco -override "tag=Experiment1 f=-O2 -march=native"

note:
  snap_perf is designed to handle only performance schedule files (e.g., grco-gcc-perf.cfg, grco-llvm-perf.cfg).
  The utility works with just one test suite at a time, but can run multiple tests and builds within it.
  For custom compilers, provide the compiler name with full path and version(s).
  Flags and tags are optional. If not provided, all configs for the suite will be processed.
  Use either -tags (multiple allowed) or -f (single flag, works as regex filter) - they are mutually exclusive.
  Use -override-flag to treat all configs as equivalent and assign default "cpu" tag.
  Use -override-tag to append a custom tag to existing tags in format: Existing-tag_New-tag.
  Use -override with key=value pairs to override specific parameters (e.g., "tag=Run1 f=-O3").
  Multiple parameters can be overridden in a single -override argument separated by spaces.
  When using -override with tag=value, it directly sets the tag (no appending behavior).
  When using -override with f=value, it overrides the compiler flags for all configs.
  Multiple tags can trigger different runtest commands for performance variability comparison.
  If -dryrun is used, shows all runtest commands and new schedule file content without execution.
  Use --save-log to preserve SLURM job logs and intermediate results. Generated runtest.sh and schedule files are saved in the same directory as perf data.
  File naming convention: /home/(user)/suitename_compiler_n/version/testname_tag.perf.data
  Long version/compiler strings are automatically truncated to prevent database warnings.
            ''')
        
        mandatory = parser.add_argument_group('mandatory arguments')
        mandatory.add_argument('-compiler', required=True,
                             help='Compiler version to use for profiling. For custom compilers, provide the full path and version (e.g., /path/to/custom/gcc-13)')
        mandatory.add_argument('-versions', required=True, nargs='+',
                             help='Specify one or more build versions for profiling (space-separated). Multiple builds can be tested within the same suite')
        mandatory.add_argument('-suite', required=True, choices=self.SUPPORTED_SUITES,
                             help='Test suite to run. Only one test suite at a time is supported')
        mandatory.add_argument('-test', required=True, nargs='+',
                             help='One or more test names to execute within the suite (space-separated). Multiple tests can be run simultaneously')
        mandatory.add_argument('-ta', required=True, 
                             help='Existing performance schedule file name (e.g., grco-gcc-perf.cfg, grco-llvm-perf.cfg). Must be a performance-specific schedule file')
        mandatory.add_argument('-user', required=True,
                             help='User identifier for the profiling session')
        
        optional = parser.add_argument_group('optional arguments')
        # Mutually exclusive group for tags or flag filtering (now optional)
        tag_group = optional.add_mutually_exclusive_group(required=False)
        tag_group.add_argument('-tags', nargs='+',
                             help='Multiple tags for test categorization - only job configs with these tags will be used')
        tag_group.add_argument('-f', dest='flag_filter',
                             help='Single flag for regex filtering (e.g., "O3", "Ofast") - works as regex filter, only one flag at a time')
        
        optional.add_argument('-override-flag', action='store_true',
                            help='Override flag mode: treat all configs as equivalent, run only one config, assign default "cpu" tag')
        optional.add_argument('-override-tag', 
                            help='Override tag mode: append this tag to existing tags in format Existing-tag_New-tag')
        optional.add_argument('-path', 
                            help='Path to save generated files')
        # Remove -coptions as it's not in the required specification
        # optional.add_argument('-coptions', 
        #                     help='Compiler options to override defaults')
        # Remove -flags as it's not in the required specification  
        # optional.add_argument('-flags', 
        #                     help='Additional flags to pass to the profiler')
        optional.add_argument('-env', nargs='*',
                            help='Space separated list of environment variables to use')
        optional.add_argument('-osversion', 
                            help='Override operating system version from schedule file')
        # Remove -utilopts as it's not in the required specification
        # optional.add_argument('-utilopts', 
        #                     help='Additional utility-specific options')
        optional.add_argument('-override', 
                            help='Override specific parameters using key=value pairs (e.g., "tag=Run1 f=-O3"). Multiple overrides can be specified in a single string separated by spaces.')
        optional.add_argument('-append', action='store_true',
                            help='Enables to append some extra options to existing ones to the extending schedule file parameters')
        optional.add_argument('-keep', action='store_true',
                            help='Keep intermediate files and results')
        optional.add_argument('-save-log', action='store_true',
                            help='Save SLURM job logs and intermediate results')
        optional.add_argument('-nosave', action='store_true',
                            help='Results do not get uploaded to the TA page')
        optional.add_argument('-utility', choices=self.SUPPORTED_UTILITIES, default='perf',
                            help='Profiling utility to use (perf) - defaults to perf')
        optional.add_argument('-extract-hotspots', action='store_true',
                            help='Automatically extract hotspots, assembly, and codegen info from generated perf data (only works with -utility perf)')
        optional.add_argument('-dryrun', action='store_true',
                            help='Show all runtest commands and new schedule file content without executing')
        optional.add_argument('-no-slurm', dest='no_slurm', action='store_true',
                            help='Run tests directly using plain runtest on the machine')
        optional.add_argument('-hotspot-top', type=int, default=10,
                            help='Number of top hotspot functions to analyze (default: 10)')
        optional.add_argument('-hotspot-threshold', type=float, default=1.0,
                            help='Minimum percentage threshold for hotspot analysis (default: 1.0)')
        optional.add_argument('-hotspot-format', choices=['txt', 'json', 'yaml'], default='txt',
                            help='Output format for hotspot analysis results (default: txt)')
        
        self.args = parser.parse_args()
        
        # Configure logging
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, 
                              format='%(levelname)s: %(message)s')
        
        return self.args
    
    def parse_override_params(self, override_string):
        """Parse override string into key-value pairs"""
        if not override_string:
            return {}
        
        overrides = {}
        # Split by spaces but handle quoted values
        import shlex
        try:
            parts = shlex.split(override_string)
        except ValueError:
            # Fallback to simple split if shlex fails
            parts = override_string.split()
        
        for part in parts:
            if '=' in part:
                key, value = part.split('=', 1)
                overrides[key.strip()] = value.strip()
            else:
                logging.warning(f"Invalid override format: {part}. Expected key=value format.")
        
        return overrides
    
    def validate_args(self):
        if not os.path.exists(self.args.ta):
            raise SnapPerfError(f"Schedule file not found: {self.args.ta}")
        
        if self.args.path and not os.path.isdir(self.args.path):
            try:
                os.makedirs(self.args.path)
            except OSError as e:
                raise SnapPerfError(f"Cannot create output directory {self.args.path}: {e}")
    
    def load_schedule_file(self):
        filter_suite = getattr(self.args, 'suite', None)
        filter_tags = getattr(self.args, 'tags', None)
        filter_flag = getattr(self.args, 'flag_filter', None)
        override_flag = getattr(self.args, 'override_flag', False)
        override_tag = getattr(self.args, 'override_tag', None)
        
        # Parse new override format if provided
        override_params = {}
        if hasattr(self.args, 'override') and self.args.override:
            override_params = self.parse_override_params(self.args.override)
            logging.info(f"Override parameters: {override_params}")
            
            # Check for tag override in the new format - should append to existing tags
            if 'tag' in override_params:
                override_tag = override_params['tag']  # This will be appended to existing tags
            
            # Check for flag override in the new format  
            # If 'f' is provided, enable flag override mode regardless of tag presence
            if 'f' in override_params:
                override_flag = True  # Enable flag override mode
        
        self.schedule_parser = ScheduleFileParser(
            self.args.ta, filter_suite, filter_tags, filter_flag, 
            override_flag, override_tag
        )
        
        # Store override params for later use
        self.override_params = override_params
        
        logging.info(f"Loaded schedule file: {self.args.ta}")
        logging.info(f"Found {len(self.schedule_parser.sections)} total sections")
        if filter_suite:
            logging.info(f"Filtering by suite: {filter_suite}")
        
        if override_params:
            logging.info(f"Using parameter overrides: {override_params}")
        elif override_flag:
            logging.info(f"Override flag mode: treating all configs as equivalent, using default 'cpu' tag")
        elif override_tag:
            logging.info(f"Override tag mode: appending '{override_tag}' to existing tags")
        elif filter_tags:
            logging.info(f"Found {self.schedule_parser.get_matching_configs_count()} sections matching tags '{filter_tags}' for suite '{filter_suite}'")
        elif filter_flag:
            logging.info(f"Found {self.schedule_parser.get_matching_configs_count()} sections matching flag '{filter_flag}' for suite '{filter_suite}'")
    
    def get_effective_values(self):
        defaults = self.schedule_parser.get_default_values()
        effective = {}
        
        # Compiler is now mandatory from command line
        effective['compiler'] = self.args.compiler
        
        # Check if we have override parameters from the new format
        override_params = getattr(self, 'override_params', {})
        
        # Handle other optional parameters with override/append logic
        for key in ['osversion', 'env', 'f']:
            cmd_value = getattr(self.args, key, None) if hasattr(self.args, key) else None
            
            # Check for override in the new format first
            if key in override_params:
                effective[key] = override_params[key]
            elif hasattr(self.args, 'override') and self.args.override and cmd_value is not None:
                effective[key] = cmd_value
            elif self.args.append and cmd_value is not None:
                # Append mode: combine with defaults
                default_value = defaults.get(key, '')
                if default_value and cmd_value:
                    effective[key] = f"{default_value} {cmd_value}"
                else:
                    effective[key] = cmd_value or default_value
            else:
                # Use command line value if provided, otherwise use defaults
                effective[key] = cmd_value if cmd_value is not None else defaults.get(key, '')
        
        effective['user'] = self.args.user
        effective['suite'] = self.args.suite
        effective['utility'] = self.args.utility
        
        # Handle tags - check override parameters first
        if 'tag' in override_params:
            # Tag override from new format - the tag appending is already handled in filtering phase
            # Just use the tag from the matched section which already has the appended format
            matched_section = self.schedule_parser.get_default_values()
            effective['tag'] = matched_section.get('tag', '')
        elif hasattr(self.args, 'tags') and self.args.tags:
            # For tags, use the tag from the first matched section
            matched_section = self.schedule_parser.get_default_values()
            effective['tag'] = matched_section.get('tag', '')
        elif hasattr(self.args, 'flag_filter') and self.args.flag_filter:
            # For flag filter, we need to get the tag from the matched section
            matched_section = self.schedule_parser.get_default_values()
            effective['tag'] = matched_section.get('tag', '')
        
        if self.args.env:
            effective['env'] = ' '.join(self.args.env)
        
        return effective
    
    def get_effective_values_for_section(self, section):
        """Get effective values for a specific section instead of just the first filtered section"""
        effective = {}
        
        # Compiler is now mandatory from command line
        effective['compiler'] = self.args.compiler
        
        # Check if we have override parameters from the new format
        override_params = getattr(self, 'override_params', {})
        
        # Handle other optional parameters with override/append logic
        for key in ['osversion', 'env', 'f']:
            cmd_value = getattr(self.args, key, None) if hasattr(self.args, key) else None
            
            # Check for override in the new format first
            if key in override_params:
                effective[key] = override_params[key]
            elif hasattr(self.args, 'override') and self.args.override and cmd_value is not None:
                effective[key] = cmd_value
            elif self.args.append and cmd_value is not None:
                # Append mode: combine with defaults
                default_value = section['params'].get(key, '')
                if default_value and cmd_value:
                    effective[key] = f"{default_value} {cmd_value}"
                else:
                    effective[key] = cmd_value or default_value
            else:
                # Use command line value if provided, otherwise use section defaults
                effective[key] = cmd_value if cmd_value is not None else section['params'].get(key, '')
        
        effective['user'] = self.args.user
        effective['suite'] = self.args.suite
        effective['utility'] = self.args.utility
        
        # Handle tags - check override parameters first
        if 'tag' in override_params:
            # Tag override from new format - the tag appending is already handled in filtering phase
            # Just use the tag from the section which already has the appended format
            effective['tag'] = section['params'].get('tag', '')
        elif hasattr(self.args, 'tags') and self.args.tags:
            # Use the original tag from the section, not the command line tags
            effective['tag'] = section['params'].get('tag', '')
        elif hasattr(self.args, 'flag_filter') and self.args.flag_filter:
            # For flag filter, use the tag from this specific section
            effective['tag'] = section['params'].get('tag', '')
        else:
            # Use the tag from this specific section
            effective['tag'] = section['params'].get('tag', '')
        
        if self.args.env:
            effective['env'] = ' '.join(self.args.env)
        
        return effective
    
    def get_next_directory_number(self, base_path, suite_compiler_prefix):
        """Find the next available directory number for the given prefix"""
        import glob
        import re
        
        # Pattern to match existing directories (both old and new format)
        pattern_old = os.path.join(base_path, f"{suite_compiler_prefix}_perf_*")
        pattern_new = os.path.join(base_path, f"{suite_compiler_prefix}_*")
        existing_dirs_old = glob.glob(pattern_old)
        existing_dirs_new = glob.glob(pattern_new)
        existing_dirs = existing_dirs_old + existing_dirs_new
        
        if not existing_dirs:
            return 0
        
        # Extract numbers from existing directories
        numbers = []
        for dir_path in existing_dirs:
            dir_name = os.path.basename(dir_path)
            # Match both old format (_perf_N) and new format (_N)
            match = re.search(r'_perf_(\d+)$', dir_name) or re.search(r'_(\d+)$', dir_name)
            if match:
                numbers.append(int(match.group(1)))
        
        if not numbers:
            return 0
        
        # Return the next number
        return max(numbers) + 1
    
    def get_output_directory_info(self):
        """Get the output directory information, calculating the number once and caching it"""
        if self._dir_number is not None:
            # Return cached values
            base_path = self.args.path if self.args.path else os.path.expanduser("~")
            effective_values = self.get_effective_values()
            safe_compiler = effective_values['compiler'].replace('/', '_').replace(' ', '_')
            suite_compiler_prefix = f"{effective_values['suite']}_{safe_compiler}"
            suite_compiler_dir = f"{suite_compiler_prefix}_{self._dir_number}"
            return base_path, suite_compiler_prefix, self._dir_number, suite_compiler_dir
        
        # Calculate for the first time
        base_path = self.args.path if self.args.path else os.path.expanduser("~")
        effective_values = self.get_effective_values()
        safe_compiler = effective_values['compiler'].replace('/', '_').replace(' ', '_')
        suite_compiler_prefix = f"{effective_values['suite']}_{safe_compiler}"
        self._dir_number = self.get_next_directory_number(base_path, suite_compiler_prefix)
        suite_compiler_dir = f"{suite_compiler_prefix}_{self._dir_number}"
        
        return base_path, suite_compiler_prefix, self._dir_number, suite_compiler_dir
    
    def show_individual_runtest_commands(self):
        """Show individual runtest commands for each combination in dry run mode"""
        # Get all filtered sections that match the suite and tag/flag criteria
        filtered_sections = self.schedule_parser.get_filtered_sections()
        
        combinations = []
        for section in filtered_sections:
            for version in self.args.versions:
                for test in self.args.test:
                    combinations.append((section, version, test))
        
        for i, (section, version, test) in enumerate(combinations, 1):
            # Generate the runtest command for this combination
            effective_values = self.get_effective_values_for_section(section)
            runtest_cmd = self.generate_individual_runtest_command(effective_values, version, test)
            print(f"{i:2d}. {runtest_cmd}")
    
    def generate_individual_runtest_command(self, effective_values, version, test):
        """Generate the individual runtest command for a specific version/test combination"""
        # Base runtest command
        cmd_parts = ['runtest']
        
        # Add compiler
        cmd_parts.extend(['-compiler', effective_values['compiler']])
        
        # Add version
        cmd_parts.extend(['-version', version])
        
        # Add user
        cmd_parts.extend(['-user', effective_values['user']])
        
        # Add suite
        cmd_parts.extend(['-suite', effective_values['suite']])
        
        # Add test
        cmd_parts.extend(['-test', test])
        
        # Add OS version if present
        if effective_values.get('osversion'):
            cmd_parts.extend(['-osversion', effective_values['osversion']])
        
        # Add environment variables if present
        if effective_values.get('env'):
            cmd_parts.extend(['-env', f"'{effective_values['env']}'"]) 
        
        # Add compiler flags if present
        if effective_values.get('f'):
            cmd_parts.extend(['-f', f"'{effective_values['f']}'"]) 
        
        # Add make command with perf
        make_cmd = self.generate_make_command_for_individual(effective_values, version, test)
        cmd_parts.extend(['-make', f"'{make_cmd}'"]) 
        
        # Add utility flags
        if self.args.utility == 'perf':
            cmd_parts.append('-perf')
        
        # Add other common flags
        cmd_parts.append('-ustack')
        cmd_parts.append('-cleanenv')
        
        # Add keep flag (always added by default)
        cmd_parts.append('-keep')
        
        if self.args.nosave:
            cmd_parts.append('-nosave')
        
        return ' '.join(cmd_parts)
    
    def generate_make_command_for_individual(self, effective_values, version, test):
        """Generate make command for individual runtest commands (not template)"""
        # Use the new directory structure: /home/(user)/suitename_compiler_n/version/
        if self.args.path:
            base_output_path = self.args.path
        else:
            base_output_path = os.path.expanduser("~")
        
        safe_version = version.replace('/', '_').replace(' ', '_')
        safe_test = test.replace('/', '_').replace(' ', '_')
        
        # Create the new directory structure: /home/(user)/suitename_compiler_n/version/
        base_output_path, suite_compiler_prefix, dir_number, suite_compiler_dir = self.get_output_directory_info()
        safe_tag = effective_values.get('tag', '').replace('/', '_').replace(' ', '_')
        
        # New structure: main_dir/version/
        version_dir = os.path.join(base_output_path, suite_compiler_dir, safe_version)
        
        # Ensure the version directory exists
        try:
            os.makedirs(version_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f"Could not create version directory {version_dir}: {e}")
            version_dir = os.path.join(base_output_path, suite_compiler_dir)
        
        # Generate the new naming convention: testname_tag.perf.data (no version prefix)
        perf_filename = f"{safe_test}_{safe_tag}.perf.data"
        perf_output = os.path.join(version_dir, perf_filename)
        
        if self.args.utility == 'perf':
            make_cmd = f'RUN="taskset 0x2 perf record -o {perf_output}"'
            
            # Track generated perf files for potential hotspot extraction (avoid duplicates)
            if perf_output not in self.generated_perf_files:
                self.generated_perf_files.append(perf_output)
        else:
            make_cmd = 'RUN="taskset 0x2"'
        
        return make_cmd
    
    def generate_section_header(self, effective_values, version, test):
        tag_part = f" {effective_values.get('tag', '')}" if effective_values.get('tag') else ""
        # Remove test_part - test name should not be in header
        # test_part = f" {test}" if test != 'all' else ""
        
        # Find the section that matches our specific tag
        matching_header = ""
        target_tag = effective_values.get('tag', '')
        
        for section in self.schedule_parser.sections:
            section_tag = section['params'].get('tag', '').strip()
            if section_tag == target_tag:
                matching_header = section['header']
                break
        
        # If no exact match found, use the first filtered section
        if not matching_header and self.schedule_parser.filtered_sections:
            matching_header = self.schedule_parser.filtered_sections[0]['header']
        
        # Extract the number in parentheses from matching header if present
        number_match = re.search(r'\((\d+)\)', matching_header)
        number_part = f" ({number_match.group(1)})" if number_match else ""
        
        header = f"[{effective_values['compiler']} {version} {effective_values['suite']}{tag_part}{number_part}"
        
        # Extract sbatch part from matching header
        sbatch_match = re.search(r'\|\s*(sbatch.*?)\]', matching_header)
        if sbatch_match:
            header += f" | {sbatch_match.group(1)}"
        else:
            header += f" | sbatch --exclusive --partition perf"
        
        header += "]"  # Only one closing bracket
        return header
    
    def generate_section_header_for_section(self, effective_values, version, section):
        """Generate section header for a specific section"""
        tag_part = f" {effective_values.get('tag', '')}" if effective_values.get('tag') else ""
        
        # Use the original header from this specific section
        original_header = section['header']
        
        # Extract the number in parentheses from original header if present
        number_match = re.search(r'\((\d+)\)', original_header)
        number_part = f" ({number_match.group(1)})" if number_match else ""
        
        header = f"[{effective_values['compiler']} {version} {effective_values['suite']}{tag_part}{number_part}"
        
        # Extract sbatch part from original header
        sbatch_match = re.search(r'\|\s*(sbatch.*?)\]', original_header)
        if sbatch_match:
            header += f" | {sbatch_match.group(1)}"
        else:
            header += f" | sbatch --exclusive --partition perf"
        
        header += "]"  # Only one closing bracket
        return header
    
    def generate_make_command(self, effective_values, version, test):
        # Use the required directory structure: /home/(user)/suitename_compiler_perf_n/
        if self.args.path:
            base_output_path = self.args.path
        else:
            base_output_path = os.path.expanduser("~")
        
        safe_version = version.replace('/', '_').replace(' ', '_')
        safe_test = test.replace('/', '_').replace(' ', '_')
        
        # Create the required directory structure: /home/(user)/suitename_compiler_perf_n/
        base_output_path, suite_compiler_prefix, dir_number, suite_compiler_perf_dir = self.get_output_directory_info()
        effective_values = self.get_effective_values()
        safe_compiler = effective_values['compiler'].replace('/', '_').replace(' ', '_')
        safe_tag = effective_values.get('tag', '').replace('/', '_').replace(' ', '_')
        perf_dir = os.path.join(base_output_path, suite_compiler_perf_dir)
        
        # Ensure the directory exists
        try:
            os.makedirs(perf_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f"Could not create perf directory {perf_dir}: {e}")
            perf_dir = base_output_path
        
        # Generate the required naming convention: version_testname_tag.perf.data
        perf_filename = f"{safe_version}_{safe_test}_{safe_tag}.perf.data"
        perf_output = os.path.join(perf_dir, perf_filename)
        
        if self.args.utility == 'perf':
            make_cmd = f'RUN="taskset 0x2 perf record -o {perf_output}"'
            
            # Track generated perf files for potential hotspot extraction (avoid duplicates)
            if perf_output not in self.generated_perf_files:
                self.generated_perf_files.append(perf_output)
        else:
            make_cmd = 'RUN="taskset 0x2"'
        
        return make_cmd
    
    def truncate_for_database(self, value, max_length=50):
        """Truncate strings to prevent database column truncation warnings.
        
        Args:
            value: String value to truncate
            max_length: Maximum length allowed (default 50 chars)
            
        Returns:
            Truncated string with indication if truncation occurred
        """
        if not value or len(value) <= max_length:
            return value
        
        # Truncate but keep meaningful parts
        truncated = value[:max_length-3] + "..."
        logging.warning(f"Version/compiler string truncated for database: '{value}' -> '{truncated}'")
        return truncated

    def generate_schedule_content(self):
        content = ""
        
        # Get all filtered sections that match the suite and tag/flag criteria
        filtered_sections = self.schedule_parser.get_filtered_sections()
        
        if not filtered_sections:
            raise SnapPerfError("No matching sections found in schedule file")
        
        logging.info(f"Found {len(filtered_sections)} matching sections for suite '{self.args.suite}'")
        logging.info(f"Generating combinations with {len(self.args.versions)} versions")
        
        # Generate all combinations: each matching section × each version
        all_configs = []
        config_counter = 0
        
        for section in filtered_sections:
            section_tag = section['params'].get('tag', '')
            logging.info(f"Processing section with tag '{section_tag}'")
            
            for version in self.args.versions:
                config_counter += 1
                
                # Create effective values for this version and section
                effective_values = self.get_effective_values_for_section(section)
                
                # Generate section header
                section_header = self.generate_section_header_for_section(effective_values, version, section)
                
                # Generate proper make command for this version - test will be substituted by runta
                base_output_path, suite_compiler_prefix, dir_number, suite_compiler_dir = self.get_output_directory_info()
                safe_version = version.replace('/', '_').replace(' ', '_')
                safe_tag = effective_values.get('tag', '').replace('/', '_').replace(' ', '_')
                
                # New structure: main_dir/version/
                version_dir = os.path.join(base_output_path, suite_compiler_dir, safe_version)
                
                # Create make command with new naming convention: testname_tag.perf.data
                perf_filename_template = f"$(TEST)_{safe_tag}.perf.data"
                perf_output = os.path.join(version_dir, perf_filename_template)
                make_command = f'RUN="taskset 0x2 perf record -o {perf_output}"'
                
                # Truncate version string to prevent database warnings
                db_safe_version = self.truncate_for_database(version, 45)
                
                # Create config data
                config_data = {
                    'header': section_header,
                    'effective_values': effective_values,
                    'section': section,
                    'version': version,
                    'db_safe_version': db_safe_version,
                    'make_command': make_command
                }
                
                all_configs.append(config_data)
        
        # Remove duplicates based on effective configuration
        unique_configs = self._remove_duplicate_configs(all_configs)
        
        logging.info(f"Generated {len(all_configs)} total configs, {len(unique_configs)} unique configs after duplicate removal")
        
        # Generate content from unique configs
        for i, config in enumerate(unique_configs):
            if i > 0:
                content += "\n\n"
            
            content += f"{config['header']}\n"
            
            if self.args.utility == 'perf':
                content += "perf : \n"
            content += "ustack : \n"
            content += "cleanenv : \n"
            
            # Truncate compiler string to prevent database warnings
            db_safe_compiler = self.truncate_for_database(config['effective_values'].get('compiler', ''), 45)
            content += f"compiler : {db_safe_compiler}\n"
            content += f"user : {config['effective_values']['user']}\n"
            content += f"suite : {config['effective_values']['suite']}\n"
            
            if 'jobs' in config['section']['params']:
                content += f"jobs : {config['section']['params']['jobs']}\n"
            
            content += f"osversion : {config['effective_values'].get('osversion', '')}\n"
            
            if config['effective_values'].get('env'):
                env_value = config['effective_values']['env'].strip("'\"")  # Remove any existing quotes
                content += f"env : '{env_value}'\n"
            
            if config['effective_values'].get('f'):
                f_value = config['effective_values']['f'].strip("'\"")  # Remove any existing quotes
                content += f"f : '{f_value}'\n"
            
            content += f"make : '{config['make_command']}'\n"
            content += f"version : {config['db_safe_version']}\n"
            
            if config['effective_values'].get('tag'):
                content += f"tag : {config['effective_values']['tag']}\n"
            
            # Don't add test field - will be handled by runta --override test=<kernel_id>
        
        return content
    
    def _remove_duplicate_configs(self, configs):
        """Remove duplicate configurations based on effective values"""
        unique_configs = []
        seen_configs = set()
        
        for config in configs:
            # Create a signature for this config based on key parameters
            # that determine if two configs are effectively the same
            effective = config['effective_values']
            signature_parts = [
                effective.get('compiler', ''),
                effective.get('suite', ''),
                effective.get('osversion', ''),
                effective.get('env', ''),
                effective.get('f', ''),
                effective.get('tag', ''),
                config['version']
            ]
            signature = '|'.join(str(part) for part in signature_parts)
            
            if signature not in seen_configs:
                seen_configs.add(signature)
                unique_configs.append(config)
            else:
                logging.debug(f"Removing duplicate config: {signature}")
        
        return unique_configs
    
    def write_schedule_file(self, content):
        # Schedule file should be saved in the main directory
        if self.args.path:
            base_output_path = self.args.path
        else:
            base_output_path = os.path.expanduser("~")
        
        # Get the effective values to determine the directory
        base_output_path, suite_compiler_prefix, dir_number, suite_compiler_dir = self.get_output_directory_info()
        output_dir = os.path.join(base_output_path, suite_compiler_dir)
        
        # Ensure the directory exists
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f"Could not create output directory {output_dir}: {e}")
            output_dir = os.path.dirname(self.args.ta) or '.'
        
        # New naming convention: suitename_compiler.cfg (no "perf")
        effective_values = self.get_effective_values()
        safe_compiler = effective_values['compiler'].replace('/', '_').replace(' ', '_')
        filename = f"{effective_values['suite']}_{safe_compiler}.cfg"
        self.output_file = os.path.join(output_dir, filename)
        
        with open(self.output_file, 'w') as f:
            f.write(content)
        
        # Calculate the correct count based on unique configs generated
        job_configs_count = content.count('[')  # Count the number of sections
        total_perf_files = job_configs_count * len(self.args.test)
        logging.info(f"Generated schedule file with {job_configs_count} job configs")
        logging.info(f"Each test will generate {job_configs_count} perf files (one per config)")
        logging.info(f"Total perf files to be generated: {total_perf_files}")
        logging.info(f"Schedule file: {self.output_file}")
        return self.output_file
    
    def generate_runtest_script(self):
        """Generate runtest.sh script in the main directory"""
        # Get the main directory
        if self.args.path:
            base_output_path = self.args.path
        else:
            base_output_path = os.path.expanduser("~")
        
        base_output_path, suite_compiler_prefix, dir_number, suite_compiler_dir = self.get_output_directory_info()
        output_dir = os.path.join(base_output_path, suite_compiler_dir)
        
        # Ensure the directory exists
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f"Could not create output directory {output_dir}: {e}")
            output_dir = os.path.dirname(self.args.ta) or '.'
        
        # Generate runtest.sh content
        runta_path = '/proj/ta/bin/runta'
        if not os.path.exists(runta_path):
            # Fallback to local runta.py if the main one doesn't exist
            runta_path = os.path.join(os.path.dirname(__file__), 'runta.py')
            if not os.path.exists(runta_path):
                runta_path = 'runta.py'
        
        cmd_parts = [runta_path, self.output_file]
        
        # For /proj/ta/bin/runta, we don't need -user argument
        # Add --no-slurm if specified (incompatible with --save-log)
        if hasattr(self.args, 'no_slurm') and self.args.no_slurm:
            cmd_parts.append('--no-slurm')
        else:
            # Add --save-log only if explicitly requested (only when not using --no-slurm)
            if hasattr(self.args, 'save_log') and self.args.save_log:
                cmd_parts.append('--save-log')
        
        # Add --dryrun if specified
        if self.args.dryrun:
            cmd_parts.append('--dryrun')
        
        # nosave might not be applicable to /proj/ta/bin/runta
        if self.args.nosave:
            pass
        
        runtest_script_path = os.path.join(output_dir, 'runtest.sh')
        runtest_command = ' '.join(cmd_parts)
        
        with open(runtest_script_path, 'w') as f:
            f.write('#!/bin/bash\n')
            f.write(f'# Generated by snap_perf on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write(f'#\n')
            f.write(f'# Original snap_perf command executed by user:\n')
            f.write(f'# {" ".join(sys.argv)}\n')
            f.write(f'#\n')
            f.write(f'# Individual runta commands that will be executed:\n')
            f.write(f'\n')
            
            # Generate individual test commands (one per test, processes all versions)
            effective_values = self.get_effective_values()
            test_num = 1
            for test in self.args.test:
                individual_cmd = [runta_path, self.output_file]
                
                # Add --no-slurm if specified
                if hasattr(self.args, 'no_slurm') and self.args.no_slurm:
                    individual_cmd.append('--no-slurm')
                else:
                    if hasattr(self.args, 'save_log') and self.args.save_log:
                        individual_cmd.append('--save-log')
                
                # Add --dryrun if specified
                if self.args.dryrun:
                    individual_cmd.append('--dryrun')
                
                # Add test override only - let runta process all versions in schedule file
                individual_cmd.extend(['--override', f'test={test}'])
                
                f.write(f'# Runta command {test_num}: test={test} (processes all {len(self.args.versions)} versions)\n')
                f.write(f'# This will generate {len(self.args.versions)} perf files: ')
                for i, version in enumerate(self.args.versions):
                    safe_version = version.replace('/', '_').replace(' ', '_')
                    safe_tag = effective_values.get('tag', '').replace('/', '_').replace(' ', '_')
                    perf_file = f"{safe_version}/{test}_{safe_tag}.perf.data"
                    if i > 0:
                        f.write(', ')
                    f.write(perf_file)
                f.write('\n')
                f.write(f'{" ".join(individual_cmd)}\n')
                f.write(f'\n')
                test_num += 1
            
            f.write(f'# Equivalent runtest commands that runta will fire:\n')
            f.write(f'\n')
            
            # Summary of execution
            total_combinations = len(self.args.versions) * len(self.args.test)
            f.write(f'# Note: Each runta command above will internally generate runtest commands\n')
            f.write(f'# for all {len(self.args.versions)} versions in the schedule file.\n')
            f.write(f'# Total runta commands: {len(self.args.test)}\n')
            f.write(f'# Total runtest commands that will be executed: {len(self.args.test)} tests × {len(self.args.versions)} versions = {total_combinations}\n')
            f.write(f'# Expected perf files: {total_combinations}\n')
            f.write(f'\n')
            
            f.write(f'# Basic command (without individual test overrides):\n')
            f.write(f'# {runtest_command}\n')
        
        # Make the script executable
        os.chmod(runtest_script_path, 0o755)
        
        logging.info(f"Generated runtest.sh script: {runtest_script_path}")
        return runtest_script_path, runtest_command
    
    def run_runta(self):
        runta_path = '/proj/ta/bin/runta'
        if not os.path.exists(runta_path):
            # Fallback to local runta.py if the main one doesn't exist
            runta_path = os.path.join(os.path.dirname(__file__), 'runta.py')
            if not os.path.exists(runta_path):
                runta_path = 'runta.py'
        
        # Execute runta once per test - each runta processes all versions in schedule file
        all_success = True
        for test in self.args.test:
            cmd = [runta_path, self.output_file]
        
            # For /proj/ta/bin/runta, we don't need -user argument
            # Add --no-slurm if specified (incompatible with --save-log)
            if hasattr(self.args, 'no_slurm') and self.args.no_slurm:
                cmd.append('--no-slurm')
            else:
                # Add --save-log only if explicitly requested (only when not using --no-slurm)
                if hasattr(self.args, 'save_log') and self.args.save_log:
                    cmd.append('--save-log')
            
            # Add --dryrun if specified
            if self.args.dryrun:
                cmd.append('--dryrun')
            
            # Override only the test - runta will process all versions in the schedule file
            cmd.extend(['--override', f'test={test}'])
            
            # Add --dryrun if specified (nosave equivalent might not be needed for /proj/ta/bin/runta)
            if self.args.nosave:
                pass  # nosave might not be applicable to /proj/ta/bin/runta
            
            if self.args.dryrun:
                logging.info(f"DRY RUN - Would execute runta for test {test}: {' '.join(cmd)}")
                logging.info(f"DRY RUN - This will process all {len(self.args.versions)} versions in the schedule file")
                # Still execute runta with --dryrun flag to see what it would do
            
            logging.info(f"Executing runta for test {test}: {' '.join(cmd)}")
            logging.info(f"This will process all {len(self.args.versions)} versions in the schedule file")
            
            try:
                # Use subprocess.Popen to stream output in real-time
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                         text=True, bufsize=1, universal_newlines=True)
                
                # Stream output line by line
                for line in process.stdout:
                    print(line, end='')
                
                # Wait for process to complete
                return_code = process.wait()
                
                if return_code == 0:
                    logging.info(f"Runta execution completed successfully for test {test}")
                    logging.info(f"Generated {len(self.args.versions)} perf files for test {test}")
                else:
                    logging.error(f"Runta execution failed for test {test} with return code {return_code}")
                    all_success = False
                    
            except Exception as e:
                logging.error(f"Runta execution failed for test {test}: {e}")
                all_success = False
            except FileNotFoundError:
                logging.error(f"Runta script not found: {runta_path}")
                all_success = False
        
        return all_success
    
    def extract_hotspots_from_perf_data(self):
        """Extract hotspots from generated perf data files if requested"""
        if not self.args.extract_hotspots:
            return True
            
        if self.args.utility != 'perf':
            logging.warning("Hotspot extraction only supported with perf utility")
            return True
            
        if not PerfHotspotExtractor:
            logging.error("Hotspot extraction module not available")
            return False
            
        logging.info("Starting automatic hotspot extraction...")
        
        success_count = 0
        total_files = len(self.generated_perf_files)
        
        for perf_file in self.generated_perf_files:
            try:
                # Wait a bit for the file to be fully written
                import time
                time.sleep(2)
                
                # Check if file exists and has some content
                if not os.path.exists(perf_file) or os.path.getsize(perf_file) < 1024:
                    logging.warning(f"Perf file {perf_file} does not exist or is too small, skipping")
                    continue
                
                logging.info(f"Extracting hotspots from: {os.path.basename(perf_file)}")
                
                # Create extractor instance
                extractor = PerfHotspotExtractor(
                    perf_file,
                    output_dir=os.path.dirname(perf_file),
                    top_functions=self.args.hotspot_top,
                    min_percentage=self.args.hotspot_threshold
                )
                
                # Run extraction
                success = extractor.run_extraction(self.args.hotspot_format)
                
                if success:
                    success_count += 1
                    base_name = os.path.splitext(os.path.basename(perf_file))[0]
                    hotspots_file = os.path.join(os.path.dirname(perf_file), f"{base_name}_hotspots.txt")
                    assembly_file = os.path.join(os.path.dirname(perf_file), f"{base_name}_assembly.txt")
                    
                    logging.info(f"Successfully extracted hotspots from: {os.path.basename(perf_file)}")
                    logging.info(f"  Generated: {os.path.basename(hotspots_file)}")
                    logging.info(f"  Generated: {os.path.basename(assembly_file)}")
                else:
                    logging.error(f"Failed to extract hotspots from: {os.path.basename(perf_file)}")
                    
            except Exception as e:
                logging.error(f"Error during hotspot extraction for {os.path.basename(perf_file)}: {e}")
        
        logging.info(f"Hotspot extraction completed: {success_count}/{total_files} files processed successfully")
        return success_count > 0 or total_files == 0
    
    def cleanup(self):
        # Per architectural requirements, schedule files should be kept in the same directory as perf data
        # Always preserve the schedule file as it should be kept alongside perf data
        if self.output_file and os.path.exists(self.output_file):
            logging.info(f"Schedule file preserved: {self.output_file}")
            if self.args and hasattr(self.args, 'dryrun') and self.args.dryrun:
                logging.info("Note: Schedule file is preserved even in dry run mode for reference")
    
    def run(self):
        try:
            self.parse_args()
            self.validate_args()
            self.load_schedule_file()
            
            filtered_sections_count = len(self.schedule_parser.get_filtered_sections())
            max_possible_configs = filtered_sections_count * len(self.args.versions)  # sections × versions
            logging.info(f"Processing {len(self.args.versions)} versions, {filtered_sections_count} matching sections for suite '{self.args.suite}', and {len(self.args.test)} tests")
            logging.info(f"Will generate up to {max_possible_configs} job configs (after duplicate removal)")
            logging.info(f"Will execute {len(self.args.test)} runta commands (one per test)")
            logging.info(f"Versions: {', '.join(self.args.versions)}")
            logging.info(f"Tests: {', '.join(self.args.test)}")
            
            # Show output path structure according to new requirements
            base_path, suite_compiler_prefix, dir_number, suite_compiler_dir = self.get_output_directory_info()
            logging.info(f"Output structure: {base_path}/{suite_compiler_dir}/{{version}}/{{testname}}_{{tag}}.perf.data")
            if hasattr(self.args, 'tags') and self.args.tags:
                logging.info(f"Tags: {', '.join(self.args.tags)}")
            elif hasattr(self.args, 'flag_filter') and self.args.flag_filter:
                logging.info(f"Flag filter: {self.args.flag_filter}")
            
            schedule_content = self.generate_schedule_content()
            schedule_file = self.write_schedule_file(schedule_content)
            
            # Generate runtest.sh script
            runtest_script_path, runtest_command = self.generate_runtest_script()
            
            if self.args.dryrun:
                # Show individual runtest commands for each combination
                print("\nINFO: DRY RUN - Individual runtest commands that would be generated:")
                print("=" * 60)
                self.show_individual_runtest_commands()
                print("=" * 60)
                
                print("\nINFO: DRY RUN - Generated schedule content:")
                print("=" * 50)
                print(schedule_content)
                print("=" * 50)
                print(f"\nINFO: DRY RUN - Would execute runta: {runtest_command}")
            else:
                print("\nINFO: Generated schedule content:")
                print("=" * 50)
                print(schedule_content)
                print("=" * 50)
            
            success = self.run_runta()
            
            if self.args.dryrun:
                print("\nINFO: Dry run completed - no execution performed")
                return 0
            
            if not success:
                logging.error("Profiling session failed")
                return 1
            
            # Extract hotspots if requested
            hotspot_success = self.extract_hotspots_from_perf_data()
            if not hotspot_success:
                logging.warning("Hotspot extraction encountered some failures, but profiling was successful")
            
            total_perf_files = len(self.args.versions) * len(self.args.test)
            logging.info(f"Profiling session completed successfully - generated {total_perf_files} perf files")
            
            # Show summary of generated files
            if self.args.utility == 'perf' and self.generated_perf_files:
                logging.info(f"Generated {len(self.generated_perf_files)} perf data files:")
                for perf_file in self.generated_perf_files:
                    logging.info(f"  - {perf_file}")
                    
                # Show extraction summary if hotspots were extracted
                if self.args.extract_hotspots:
                    logging.info("Hotspot extraction files generated alongside perf data files:")
                    for perf_file in self.generated_perf_files:
                        base_name = os.path.splitext(os.path.basename(perf_file))[0]
                        hotspots_file = f"{base_name}_hotspots.txt"
                        assembly_file = f"{base_name}_assembly.txt"
                        logging.info(f"  For {os.path.basename(perf_file)}:")
                        logging.info(f"    - {hotspots_file}")
                        logging.info(f"    - {assembly_file}")
            
            return 0
            
        except SnapPerfError as e:
            logging.error(str(e))
            return 1
        except KeyboardInterrupt:
            logging.info("Operation cancelled by user")
            return 1
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            return 1
        finally:
            # Cleanup only for dry runs  
            if hasattr(self, 'output_file'):
                self.cleanup()

def main():
    snapperf = SnapPerf()
    return snapperf.run()

if __name__ == '__main__':
    sys.exit(main())

#EDIT after this started for custom compiler