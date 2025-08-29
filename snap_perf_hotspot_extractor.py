#!/usr/bin/env python

from __future__ import print_function

import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import defaultdict, OrderedDict
from datetime import datetime

# Optional YAML support
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logging.warning("YAML module not available, YAML output format disabled")

class PerfHotspotExtractor:
    """
    Extracts hotspots, hot function assemblies, and code generation details from perf data files.
    Designed to work seamlessly with snap_perf workflow.
    """
    
    def __init__(self, perf_data_file, output_dir=None, top_functions=10, min_percentage=1.0):
        self.perf_data_file = perf_data_file
        self.output_dir = output_dir or os.path.dirname(perf_data_file)
        self.top_functions = top_functions
        self.min_percentage = min_percentage
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize extraction results
        self.hotspots = []
        self.hot_functions = {}
        self.assembly_data = {}
        self.codegen_info = {}
        
    def validate_perf_data(self):
        """Validate that the perf data file exists and is readable by perf"""
        if not os.path.exists(self.perf_data_file):
            raise FileNotFoundError(f"Perf data file not found: {self.perf_data_file}")
        
        # Check if perf can read the file
        try:
            cmd = ['perf', 'report', '-i', self.perf_data_file, '--header-only']
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logging.info(f"Perf data file validated: {self.perf_data_file}")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Invalid perf data file {self.perf_data_file}: {e}")
            return False
        except FileNotFoundError:
            logging.error("perf command not found. Please ensure perf is installed.")
            return False
    
    def extract_hotspots(self):
        """Extract hotspot functions using perf report"""
        logging.info("Extracting hotspots from perf data...")
        
        try:
            # Get basic hotspot report
            cmd = [
                'perf', 'report', '-i', self.perf_data_file,
                '--stdio', '--sort', 'symbol,dso',
                '--percent-limit', str(self.min_percentage)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # Parse the output
            self._parse_perf_report(result.stdout)
            
            logging.info(f"Extracted {len(self.hotspots)} hotspots")
            return True
            
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to extract hotspots: {e}")
            return False
    
    def _parse_perf_report(self, report_output):
        """Parse perf report output to extract hotspot information"""
        lines = report_output.split('\n')
        in_samples_section = False
        
        for line in lines:
            line = line.strip()
            
            # Skip header and empty lines
            if not line or line.startswith('#') or line.startswith('Event count'):
                continue
            
            # Look for the samples section
            if 'Overhead' in line and 'Symbol' in line:
                in_samples_section = True
                continue
            
            if not in_samples_section:
                continue
            
            # Parse data lines
            # Format: "  12.34%  binary_name  [.] function_name"
            match = re.match(r'\s*(\d+\.\d+)%\s+(\S+)\s+\[.\]\s+(.+)', line)
            if match:
                percentage = float(match.group(1))
                binary = match.group(2)
                function = match.group(3)
                
                hotspot = {
                    'percentage': percentage,
                    'binary': binary,
                    'function': function,
                    'rank': len(self.hotspots) + 1
                }
                
                self.hotspots.append(hotspot)
                
                # Stop after getting top N functions
                if len(self.hotspots) >= self.top_functions:
                    break
    
    def extract_function_assembly(self, function_name, binary_name=None):
        """Extract assembly code for a specific hot function"""
        logging.info(f"Extracting assembly for function: {function_name}")
        
        try:
            cmd = [
                'perf', 'annotate', '-i', self.perf_data_file,
                '--stdio', function_name
            ]
            
            if binary_name:
                cmd.extend(['--dso', binary_name])
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # Parse annotate output
            assembly_info = self._parse_perf_annotate(result.stdout, function_name)
            
            if assembly_info:
                self.assembly_data[function_name] = assembly_info
                logging.info(f"Extracted assembly for {function_name}")
                return assembly_info
            
        except subprocess.CalledProcessError as e:
            logging.warning(f"Failed to extract assembly for {function_name}: {e}")
            return None
    
    def _parse_perf_annotate(self, annotate_output, function_name):
        """Parse perf annotate output to extract assembly and hotspot information"""
        lines = annotate_output.split('\n')
        assembly_lines = []
        total_samples = 0
        hottest_lines = []
        
        in_function = False
        current_address = None
        
        for line in lines:
            # Skip header lines
            if line.startswith('Percent'):
                in_function = True
                continue
                
            if not in_function:
                continue
            
            # Parse assembly lines with sample data
            # Format: " 12.34 :   400abc:   mov    %rax,%rbx"
            match = re.match(r'\s*(\d+\.\d+)?\s*:\s*([0-9a-fA-F]+):\s*(.+)', line)
            if match:
                percentage_str = match.group(1)
                address = match.group(2)
                instruction = match.group(3).strip()
                
                percentage = float(percentage_str) if percentage_str else 0.0
                
                asm_line = {
                    'address': address,
                    'instruction': instruction,
                    'percentage': percentage
                }
                
                assembly_lines.append(asm_line)
                total_samples += percentage
                
                # Track hottest lines
                if percentage > 0.5:  # Lines with >0.5% samples
                    hottest_lines.append(asm_line)
        
        if assembly_lines:
            return {
                'function': function_name,
                'total_samples_percentage': total_samples,
                'assembly_lines': assembly_lines,
                'hottest_lines': sorted(hottest_lines, key=lambda x: x['percentage'], reverse=True),
                'instruction_count': len(assembly_lines)
            }
        
        return None
    
    def extract_codegen_info(self):
        """Extract code generation information from the hottest functions"""
        logging.info("Extracting code generation information...")
        
        for hotspot in self.hotspots:
            function_name = hotspot['function']
            binary_name = hotspot['binary']
            
            logging.info(f"Processing hotspot #{hotspot['rank']}: {function_name} ({hotspot['percentage']:.2f}%)")
            
            # Get detailed assembly
            assembly_info = self.extract_function_assembly(function_name, binary_name)
            
            if assembly_info:
                # Analyze code generation patterns
                codegen_analysis = self._analyze_codegen_patterns(assembly_info)
                self.codegen_info[function_name] = codegen_analysis
                logging.info(f"Extracted assembly and codegen for {function_name}")
            else:
                logging.warning(f"Could not extract assembly for {function_name}")
    
    def _analyze_codegen_patterns(self, assembly_info):
        """Analyze assembly code to extract code generation insights"""
        patterns = {
            'vectorization': {
                'count': 0,
                'instructions': [],
                'types': set()
            },
            'loop_optimizations': {
                'unrolling_detected': False,
                'jump_count': 0,
                'jump_instructions': []
            },
            'memory_access': {
                'load_count': 0,
                'store_count': 0,
                'addressing_modes': set()
            },
            'arithmetic': {
                'integer_ops': 0,
                'float_ops': 0,
                'simd_ops': 0
            }
        }
        
        for asm_line in assembly_info['assembly_lines']:
            instruction = asm_line['instruction'].lower()
            
            # Detect vectorization patterns
            if any(vec_prefix in instruction for vec_prefix in ['vmov', 'vadd', 'vmul', 'vfma', 'xmm', 'ymm', 'zmm']):
                patterns['vectorization']['count'] += 1
                patterns['vectorization']['instructions'].append(asm_line)
                
                # Determine vector width
                if 'ymm' in instruction:
                    patterns['vectorization']['types'].add('AVX/AVX2 256-bit')
                elif 'zmm' in instruction:
                    patterns['vectorization']['types'].add('AVX-512 512-bit')
                elif 'xmm' in instruction:
                    patterns['vectorization']['types'].add('SSE 128-bit')
            
            # Detect loop optimizations
            if any(jump_instr in instruction for jump_instr in ['jmp', 'je', 'jne', 'jl', 'jg', 'loop']):
                patterns['loop_optimizations']['jump_count'] += 1
                patterns['loop_optimizations']['jump_instructions'].append(asm_line)
            
            # Detect memory access patterns
            if 'mov' in instruction and ('(' in instruction or '[' in instruction):
                if instruction.startswith('mov') and ',' in instruction:
                    # Simplified detection for loads vs stores
                    parts = instruction.split(',')
                    if '(' in parts[1] or '[' in parts[1]:  # destination is memory
                        patterns['memory_access']['store_count'] += 1
                    elif '(' in parts[0] or '[' in parts[0]:  # source is memory
                        patterns['memory_access']['load_count'] += 1
            
            # Detect arithmetic operations
            if any(arith_op in instruction for arith_op in ['add', 'sub', 'mul', 'div', 'imul', 'idiv']):
                patterns['arithmetic']['integer_ops'] += 1
            elif any(float_op in instruction for float_op in ['fadd', 'fsub', 'fmul', 'fdiv', 'addss', 'mulss']):
                patterns['arithmetic']['float_ops'] += 1
            elif any(simd_op in instruction for simd_op in ['paddd', 'pmul', 'vadd', 'vmul']):
                patterns['arithmetic']['simd_ops'] += 1
        
        # Convert sets to lists for JSON serialization
        patterns['vectorization']['types'] = list(patterns['vectorization']['types'])
        
        return patterns
    
    def generate_summary_report(self):
        """Generate a comprehensive summary report"""
        summary = {
            'metadata': {
                'perf_data_file': os.path.basename(self.perf_data_file),
                'extraction_timestamp': self.timestamp,
                'total_hotspots': len(self.hotspots),
                'analysis_parameters': {
                    'top_functions': self.top_functions,
                    'min_percentage': self.min_percentage
                }
            },
            'hotspots': self.hotspots,
            'assembly_analysis': self.assembly_data,
            'codegen_analysis': self.codegen_info
        }
        
        return summary
    
    def save_results(self, format='txt'):
        """Save extraction results to files using perf.data naming convention"""
        base_name = os.path.splitext(os.path.basename(self.perf_data_file))[0]
        
        # Generate the files following the workflow requirements
        hotspots_file = self._save_hotspots_text_file(base_name)
        assembly_file = self._save_assembly_text_file(base_name)
        
        logging.info(f"Hotspot analysis saved to: {hotspots_file}")
        logging.info(f"Assembly analysis saved to: {assembly_file}")
        
        # Also save JSON for detailed analysis if requested
        if format.lower() == 'json':
            summary = self.generate_summary_report()
            json_file = os.path.join(self.output_dir, f"{base_name}_summary.json")
            with open(json_file, 'w') as f:
                json.dump(summary, f, indent=2)
            logging.info(f"Detailed JSON summary saved to: {json_file}")
            return json_file
        elif format.lower() == 'yaml':
            if not YAML_AVAILABLE:
                logging.warning("YAML format requested but YAML module not available, using JSON instead")
                summary = self.generate_summary_report()
                json_file = os.path.join(self.output_dir, f"{base_name}_summary.json")
                with open(json_file, 'w') as f:
                    json.dump(summary, f, indent=2)
                return json_file
            else:
                summary = self.generate_summary_report()
                yaml_file = os.path.join(self.output_dir, f"{base_name}_summary.yaml")
                with open(yaml_file, 'w') as f:
                    yaml.dump(summary, f, default_flow_style=False, indent=2)
                logging.info(f"Detailed YAML summary saved to: {yaml_file}")
                return yaml_file
        
        return hotspots_file
    
    def _save_readable_summary(self, base_name):
        """Save a human-readable summary file"""
        summary_file = os.path.join(self.output_dir, f"{base_name}_hotspots_summary_{self.timestamp}.txt")
        
        with open(summary_file, 'w') as f:
            f.write(f"Hotspot Analysis Summary\n")
            f.write(f"{'='*50}\n\n")
            f.write(f"Perf Data File: {self.perf_data_file}\n")
            f.write(f"Analysis Time: {self.timestamp}\n")
            f.write(f"Total Hotspots Found: {len(self.hotspots)}\n\n")
            
            f.write("Top Hotspots:\n")
            f.write("-" * 30 + "\n")
            for i, hotspot in enumerate(self.hotspots, 1):
                f.write(f"{i:2d}. {hotspot['percentage']:6.2f}% - {hotspot['function']} ({hotspot['binary']})\n")
            
            f.write("\nCode Generation Analysis:\n")
            f.write("-" * 30 + "\n")
            for func_name, codegen in self.codegen_info.items():
                f.write(f"\nFunction: {func_name}\n")
                
                vec_info = codegen['vectorization']
                if vec_info['count'] > 0:
                    f.write(f"  Vectorization: {vec_info['count']} instructions, types: {', '.join(vec_info['types'])}\n")
                
                arith_info = codegen['arithmetic']
                f.write(f"  Arithmetic: {arith_info['integer_ops']} int, {arith_info['float_ops']} float, {arith_info['simd_ops']} SIMD\n")
                
                mem_info = codegen['memory_access']
                f.write(f"  Memory: {mem_info['load_count']} loads, {mem_info['store_count']} stores\n")
        
        logging.info(f"Readable summary saved to: {summary_file}")
    
    def _save_hotspots_text_file(self, base_name):
        """Save hotspots information in a dedicated text file following perf.data naming convention"""
        # Following naming convention: base_name_hotspots.txt (removes .perf from .perf.data)
        hotspots_file = os.path.join(self.output_dir, f"{base_name}_hotspots.txt")
        
        with open(hotspots_file, 'w') as f:
            f.write(f"Performance Hotspots Analysis\n")
            f.write(f"{'='*80}\n\n")
            f.write(f"Perf Data File: {os.path.basename(self.perf_data_file)}\n")
            f.write(f"Analysis Timestamp: {self.timestamp}\n")
            f.write(f"Total Functions Analyzed: {len(self.hotspots)}\n")
            f.write(f"Analysis Parameters:\n")
            f.write(f"  - Top Functions: {self.top_functions}\n")
            f.write(f"  - Minimum Percentage: {self.min_percentage}%\n\n")
            
            if not self.hotspots:
                f.write("No hotspots found. This may be due to:\n")
                f.write("- No functions above the minimum percentage threshold\n")
                f.write("- Perf data file contains insufficient sample data\n")
                f.write("- All functions have very low overhead\n\n")
                return hotspots_file
            
            f.write(f"{'='*80}\n")
            f.write(f"HOTSPOT FUNCTIONS (Top {len(self.hotspots)})\n")
            f.write(f"{'='*80}\n\n")
            f.write(f"Format: Rank | Percentage | Binary | Function Name\n")
            f.write(f"{'-'*80}\n")
            
            for hotspot in self.hotspots:
                rank = hotspot['rank']
                percentage = hotspot['percentage']
                binary = hotspot['binary']
                function = hotspot['function']
                
                f.write(f"{rank:4d} | {percentage:8.2f}% | {binary:20s} | {function}\n")
            
            # Add summary statistics
            f.write(f"\n{'-'*80}\n")
            f.write(f"SUMMARY STATISTICS\n")
            f.write(f"{'-'*80}\n")
            
            total_percentage = sum(hs['percentage'] for hs in self.hotspots)
            f.write(f"Total coverage of top {len(self.hotspots)} functions: {total_percentage:.2f}%\n")
            
            # Group by binary
            binary_stats = defaultdict(list)
            for hotspot in self.hotspots:
                binary_stats[hotspot['binary']].append(hotspot)
            
            f.write(f"\nHotspots by Binary:\n")
            for binary, functions in binary_stats.items():
                binary_total = sum(func['percentage'] for func in functions)
                f.write(f"  {binary}: {len(functions)} functions, {binary_total:.2f}% total\n")
            
            # Top hotspot details
            if self.hotspots:
                top_hotspot = self.hotspots[0]
                f.write(f"\nTop Hotspot Details:\n")
                f.write(f"  Function: {top_hotspot['function']}\n")
                f.write(f"  Binary: {top_hotspot['binary']}\n")
                f.write(f"  Percentage: {top_hotspot['percentage']:.2f}%\n")
                
                # Add assembly info if available
                if top_hotspot['function'] in self.assembly_data:
                    asm_info = self.assembly_data[top_hotspot['function']]
                    f.write(f"  Assembly Instructions: {asm_info['instruction_count']}\n")
                    f.write(f"  Hot Instructions (>0.5%): {len(asm_info['hottest_lines'])}\n")
        
        logging.info(f"Hotspots analysis saved to: {hotspots_file}")
        return hotspots_file
    
    def _save_assembly_text_file(self, base_name):
        """Save detailed assembly analysis in a dedicated text file following perf.data naming convention"""
        # Following naming convention: base_name_assembly.txt (removes .perf from .perf.data)
        assembly_file = os.path.join(self.output_dir, f"{base_name}_assembly.txt")
        
        with open(assembly_file, 'w') as f:
            f.write(f"Hotspot Assembly Analysis\n")
            f.write(f"{'='*80}\n\n")
            f.write(f"Perf Data File: {os.path.basename(self.perf_data_file)}\n")
            f.write(f"Analysis Timestamp: {self.timestamp}\n")
            f.write(f"Total Functions with Assembly: {len(self.assembly_data)}\n")
            f.write(f"Total Hotspots Found: {len(self.hotspots)}\n\n")
            
            if not self.assembly_data:
                f.write("No assembly data extracted. This may be due to:\n")
                f.write("- No hotspot functions found above the threshold\n")
                f.write("- Perf data file contains no sample data\n")
                f.write("- Missing debug symbols in the binaries\n")
                f.write("- Perf annotate failed to extract assembly\n")
                f.write("- Functions may be in stripped binaries\n\n")
                
                # Still show the hotspots even if assembly extraction failed
                if self.hotspots:
                    f.write("Hotspots found (without assembly details):\n")
                    f.write(f"{'-'*60}\n")
                    for i, hotspot in enumerate(self.hotspots, 1):
                        f.write(f"{i:2d}. {hotspot['percentage']:6.2f}% - {hotspot['function']} ({hotspot['binary']})\n")
                return assembly_file
            
            # Sort functions by their hotspot ranking
            hotspot_order = {hs['function']: hs['rank'] for hs in self.hotspots}
            sorted_functions = sorted(self.assembly_data.keys(), 
                                    key=lambda x: hotspot_order.get(x, 999))
            
            for i, func_name in enumerate(sorted_functions, 1):
                assembly_info = self.assembly_data[func_name]
                hotspot_info = next((hs for hs in self.hotspots if hs['function'] == func_name), None)
                
                f.write(f"{'='*80}\n")
                f.write(f"FUNCTION #{i}: {func_name}\n")
                f.write(f"{'='*80}\n")
                
                if hotspot_info:
                    f.write(f"Hotspot Rank: #{hotspot_info['rank']}\n")
                    f.write(f"Sample Percentage: {hotspot_info['percentage']:.2f}%\n")
                    f.write(f"Binary: {hotspot_info['binary']}\n")
                else:
                    f.write(f"Sample Percentage: {assembly_info['total_samples_percentage']:.2f}%\n")
                
                f.write(f"Total Instructions: {assembly_info['instruction_count']}\n")
                f.write(f"Hot Instructions (>0.5%): {len(assembly_info['hottest_lines'])}\n")
                
                # Add code generation analysis if available
                if func_name in self.codegen_info:
                    codegen = self.codegen_info[func_name]
                    f.write(f"\nCode Generation Analysis:\n")
                    f.write(f"  Vectorization: {codegen['vectorization']['count']} instructions")
                    if codegen['vectorization']['types']:
                        f.write(f" ({', '.join(codegen['vectorization']['types'])})")
                    f.write(f"\n")
                    f.write(f"  Arithmetic: {codegen['arithmetic']['integer_ops']} int, "
                           f"{codegen['arithmetic']['float_ops']} float, "
                           f"{codegen['arithmetic']['simd_ops']} SIMD\n")
                    f.write(f"  Memory: {codegen['memory_access']['load_count']} loads, "
                           f"{codegen['memory_access']['store_count']} stores\n")
                    f.write(f"  Jumps/Loops: {codegen['loop_optimizations']['jump_count']} jump instructions\n")
                
                f.write(f"\n{'-'*80}\n")
                f.write(f"ASSEMBLY CODE WITH SAMPLE DISTRIBUTION\n")
                f.write(f"{'-'*80}\n")
                f.write(f"Format: [Sample%] Address: Assembly Instruction\n")
                f.write(f"{'-'*80}\n\n")
                
                # Display assembly lines with sample percentages
                for asm_line in assembly_info['assembly_lines']:
                    percentage = asm_line['percentage']
                    address = asm_line['address']
                    instruction = asm_line['instruction']
                    
                    # Highlight hot lines
                    if percentage > 0.5:
                        marker = "🔥 "
                    elif percentage > 0.1:
                        marker = "⚡ "
                    else:
                        marker = "   "
                    
                    if percentage > 0:
                        f.write(f"{marker}[{percentage:6.2f}%] {address}: {instruction}\n")
                    else:
                        f.write(f"{marker}[      ] {address}: {instruction}\n")
                
                # Show hottest lines summary
                if assembly_info['hottest_lines']:
                    f.write(f"\n{'-'*40}\n")
                    f.write(f"HOTTEST INSTRUCTIONS (>0.5% samples)\n")
                    f.write(f"{'-'*40}\n")
                    for hot_line in assembly_info['hottest_lines'][:10]:  # Top 10
                        f.write(f"[{hot_line['percentage']:6.2f}%] {hot_line['address']}: {hot_line['instruction']}\n")
                
                f.write(f"\n\n")
        
        logging.info(f"Assembly analysis saved to: {assembly_file}")
        return assembly_file
    
    def run_extraction(self, output_format='json'):
        """Run the complete hotspot extraction process"""
        logging.info(f"Starting hotspot extraction for: {self.perf_data_file}")
        
        try:
            # Validate perf data file
            if not self.validate_perf_data():
                return False
            
            # Extract hotspots
            if not self.extract_hotspots():
                return False
            
            # Extract detailed assembly and codegen info
            self.extract_codegen_info()
            
            # Save results
            output_file = self.save_results(output_format)
            
            logging.info(f"Hotspot extraction completed successfully")
            logging.info(f"Results saved to: {output_file}")
            
            return True
            
        except Exception as e:
            logging.error(f"Hotspot extraction failed: {e}")
            return False


class PerfDataMonitor:
    """
    Monitors directories for new perf data files and automatically triggers hotspot extraction.
    """
    
    def __init__(self, monitor_dirs, extraction_params=None):
        self.monitor_dirs = monitor_dirs if isinstance(monitor_dirs, list) else [monitor_dirs]
        self.extraction_params = extraction_params or {}
        self.processed_files = set()
        
    def scan_for_perf_files(self):
        """Scan monitored directories for new perf data files"""
        new_files = []
        
        for monitor_dir in self.monitor_dirs:
            if not os.path.exists(monitor_dir):
                continue
                
            for root, dirs, files in os.walk(monitor_dir):
                for file in files:
                    if file.endswith('.data') and 'perf' in file:
                        full_path = os.path.join(root, file)
                        if full_path not in self.processed_files:
                            new_files.append(full_path)
        
        return new_files
    
    def process_new_files(self, perf_files):
        """Process newly found perf data files"""
        for perf_file in perf_files:
            logging.info(f"Processing new perf data file: {perf_file}")
            
            try:
                # Create extractor instance
                extractor = PerfHotspotExtractor(
                    perf_file,
                    **self.extraction_params
                )
                
                # Run extraction
                success = extractor.run_extraction()
                
                if success:
                    self.processed_files.add(perf_file)
                    logging.info(f"Successfully processed: {perf_file}")
                else:
                    logging.error(f"Failed to process: {perf_file}")
                    
            except Exception as e:
                logging.error(f"Error processing {perf_file}: {e}")
    
    def monitor_once(self):
        """Run one iteration of monitoring"""
        new_files = self.scan_for_perf_files()
        if new_files:
            self.process_new_files(new_files)
        return len(new_files)


def process_perf_data_directory(directory_path, top_functions=10, min_percentage=1.0):
    """
    Process all perf.data files in a directory and extract hotspots/assembly
    
    Args:
        directory_path: Path to directory containing perf.data files
        top_functions: Number of top functions to analyze
        min_percentage: Minimum percentage threshold for hotspots
        
    Returns:
        Dictionary mapping perf files to their output files
    """
    if not os.path.exists(directory_path):
        logging.error(f"Directory not found: {directory_path}")
        return {}
    
    perf_files = []
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            if file.endswith('.perf.data'):
                perf_files.append(os.path.join(root, file))
    
    if not perf_files:
        logging.warning(f"No perf.data files found in directory: {directory_path}")
        return {}
    
    logging.info(f"Found {len(perf_files)} perf.data files to process")
    
    results = {}
    successful = 0
    
    for perf_file in perf_files:
        logging.info(f"Processing: {os.path.basename(perf_file)}")
        
        try:
            extractor = PerfHotspotExtractor(
                perf_file,
                output_dir=os.path.dirname(perf_file),
                top_functions=top_functions,
                min_percentage=min_percentage
            )
            
            success = extractor.run_extraction('txt')
            
            if success:
                base_name = os.path.splitext(os.path.basename(perf_file))[0]
                hotspots_file = os.path.join(os.path.dirname(perf_file), f"{base_name}_hotspots.txt")
                assembly_file = os.path.join(os.path.dirname(perf_file), f"{base_name}_assembly.txt")
                
                results[perf_file] = {
                    'hotspots_file': hotspots_file,
                    'assembly_file': assembly_file,
                    'success': True
                }
                successful += 1
            else:
                results[perf_file] = {'success': False}
                
        except Exception as e:
            logging.error(f"Error processing {perf_file}: {e}")
            results[perf_file] = {'success': False, 'error': str(e)}
    
    logging.info(f"Processing completed: {successful}/{len(perf_files)} files processed successfully")
    return results


def main():
    """Main entry point for standalone usage"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Extract hotspots, assembly, and codegen information from perf data files"
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('perf_data_file', nargs='?', help='Path to perf.data file')
    group.add_argument('-d', '--directory', help='Process all perf.data files in directory')
    
    parser.add_argument('-o', '--output-dir', help='Output directory for results (single file mode only)')
    parser.add_argument('-n', '--top-functions', type=int, default=10,
                       help='Number of top functions to analyze (default: 10)')
    parser.add_argument('-m', '--min-percentage', type=float, default=1.0,
                       help='Minimum percentage threshold for hotspots (default: 1.0)')
    parser.add_argument('-f', '--format', choices=['txt', 'json', 'yaml'], default='txt',
                       help='Output format (default: txt)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format='%(levelname)s: %(message)s')
    
    if args.directory:
        # Process directory
        results = process_perf_data_directory(
            args.directory,
            args.top_functions,
            args.min_percentage
        )
        
        # Print summary
        successful = sum(1 for r in results.values() if r.get('success', False))
        total = len(results)
        
        print(f"\nProcessing Summary:")
        print(f"{'='*50}")
        print(f"Total files: {total}")
        print(f"Successful: {successful}")
        print(f"Failed: {total - successful}")
        
        if successful > 0:
            print(f"\nGenerated files:")
            for perf_file, result in results.items():
                if result.get('success', False):
                    print(f"  {os.path.basename(perf_file)}:")
                    print(f"    - {result['hotspots_file']}")
                    print(f"    - {result['assembly_file']}")
        
        return 0 if successful > 0 else 1
    
    else:
        # Process single file
        extractor = PerfHotspotExtractor(
            args.perf_data_file,
            args.output_dir,
            args.top_functions,
            args.min_percentage
        )
        
        success = extractor.run_extraction(args.format)
        return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
