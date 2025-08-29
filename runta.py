#!/usr/bin/env python

from __future__ import print_function

import argparse
import logging
import os
import random
import re
import shlex
import subprocess
import yaml

from six.moves import shlex_quote

from ta import configuration as conf
from ta import defaults
from ta.lib.db import DBQuery, getSuite
from ta.lib.schedule import Schedule
from ta.lib.slurm import sbatch_add_arg
from ta.lib.suitewatcher import get_suites_by_type
from ta.lib.utils import sortArgs

class KeyValue(argparse.Action):
    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        super(KeyValue, self).__init__(option_strings, dest, nargs, **kwargs)
        self._d = {}

    def __call__(self, parser, namespace, values, option_string=None):
        for kv in values:
            key, value = kv.split('=', 1)

            if value == 'true' or value == 'True':
                self._d[key] = True
            elif value == 'false' or value == 'False':
                self._d[key] = False
            else:
                if key in self._d:
                    if isinstance(self._d[key], list):
                        self._d[key].append(value)
                    elif isinstance(self._d[key], str):
                        self._d[key] = [self._d[key], value]
                    else:
                        logging.warning('unknown type')
                else:
                    self._d[key] = value
        setattr(namespace, self.dest, self._d)

def deconstruct_rtcmd(cmd):

    argv = shlex.split('runtest ' + cmd)

    for f in ['-f', '-nvccf', '-cflags', '-cxxflags', '-fcflags']:
        if f in argv and argv[-1] != f:
            flags_index = argv.index(f)+1
            argv[flags_index] = ' ' + argv[flags_index]

    rtopts = sortArgs(argv, defaults.get('options'))

    rtargs = filter(lambda x: x[0] == '-' or False, argv)

    rtargs = [re.sub(r'^\-+', '', rtarg) for rtarg in rtargs]

    rtopts = {k: rtopts[k] for k in rtargs if k in rtopts}

    for f in ['f', 'nvccf', 'cflags', 'cxxflags', 'fcflags']:
        if f in rtopts and rtopts[f][0] == ' ':
            rtopts[f] = rtopts[f][1:]

    return rtargs, rtopts

def filter_sched(sched, key, value, kind='equal'):

    if kind == 'equal':
        return list(filter(
            lambda i: i.get('rtopts', {}).get(key) == value, sched))
    elif kind == 'regex':
        return list(filter(
            lambda i: re.search(value, str(i.get('rtopts', {}).get(key))),
            sched))
    elif kind == 'slurm':
        return list(filter(
            lambda i: re.search(value, str(i.get('sbatch'))), sched))
    else:
        logging.error('Unrecognized filter kind: {}'.format(kind))
        exit(1)

def firstrun(sched, only=False):

    firstrun = []
    residual = []
    ledger = {}

    for s in sched:
        token = '{0}-{1}'.format(s.get('rtopts', {}).get('suite'),
                                 s.get('file'))
        if token not in ledger:
            s['sbatch'] = sbatch_add_arg(s['sbatch'], '--partition',
                                         'firstrun')
            firstrun.append(s)
            ledger[token] = 1
        else:

            residual.append(s)
            ledger[token] += 1

    if only:
        return firstrun
    else:
        return firstrun + residual

def get_suite_count():


    data = DBQuery('SELECT suitename, COUNT(*) + SUM(COALESCE(timeout,0)) FROM suitetests GROUP BY suitename')

    d = {}
    if data:
        for key, val in data:
            d[key] = val

    return d

def get_suite_timeout(suite):
    s = getSuite(suite)
    if s:
        return (s.ctimeout, s.etimeout)
    else:
        return (600, 600)

def lint(cmdline, dictionary, strict=True):



    count = {'count': 0}

    sbatch = dictionary.get('sbatch', '')
    rtopts = dictionary.get('rtopts', {})

    def report(reason):
        logging.warning('{0}: {1}'.format(reason, cmdline))
        count['count'] += 1

    if rtopts.get('perf'):



        if not '--exclusive' in sbatch:
            report('Performance TA not run exclusively')
    else:



        if strict and ' -w' in sbatch:
            report('Tests should not be scheduled to run on specific systems')


        if (rtopts.get('mpi') == 'hpcx' and 
            not re.search('--constraint \S*hpcx\S*', sbatch)):
            report('runtest -mpi hpcx used without requiring hpcx node property')


        if (rtopts.get('mpi') == 'openmpi4' and
            not re.search(r'--constraint \S*openmpi4\S*', sbatch)):
            report('runtest -mpi openmpi4 used without requiring openmpi4 node property')


        if (rtopts.get('mpi') == 'mpi' and (
                rtopts.get('osversion') == 'Linux_aarch64' or
                rtopts.get('osversion') == 'Linux_x86_64') and
            not re.search('--constraint \S*hpcx\S*', sbatch)):
            report('runtest -mpi mpi used without requiring hpcx node property on x86_64/aarch64')


        if (rtopts.get('mpi') == 'mpi' and 
            rtopts.get('osversion') == 'Linux_ppc64le' and
            not re.search('--constraint \S*openmpi4\S*', sbatch)):
            report('runtest -mpi mpi used without requiring openmpi4 node property on ppc64le')




    if rtopts.get('host'):
        report('runtest -host should not be used')


    if (rtopts.get('sim') == 'rungpu' and '--gpu' not in sbatch and
        not ('OMP_TARGET_OFFLOAD=DISABLED' in rtopts.get('env', '') or
             '--exclusive' in sbatch)):
        report('runtest -sim rungpu used without requesting any GPUs')


    if re.search(r'-N [2-9][0-9]*', sbatch):
        report('More than 1 node requested')


    if strict and ' -N' not in sbatch and ' -w' not in sbatch:
        report('The number of nodes is not specified')


    if rtopts.get('user') not in ['qa', 'grco']:
        report('Non qa, non grco user specified')


    try:
        shlex.split(cmdline)
    except Exception as e:
        report('Error parsing command line, {}'.format(e))
        
    return count['count']

def make_cmdline(dictionary, append={}, canonical=False, force_partition=False,
                 jobname=None, nodelist=None, override={}, partition=None, reconstruct=True,
                 slurm=True, save_log=False, suite_count={}, test_only=False,
                 time_hints=False, windows=False):



    runtest = [conf.get('runschedule', 'runtest')]
    if windows:
        runtest = [conf.get('runschedule', 'winruntest')]

    if reconstruct:

        rtargs = dictionary.get('rtargs', [])
        rtopts = dictionary.get('rtopts', {})

        if append:
            for key, value in append.items():
                if key in rtargs:
                    if isinstance(rtopts[key], list):
                        if isinstance(value, list):
                            rtopts[key].extend(value)
                        else:
                            rtopts[key].append(value)
                    elif isinstance(rtopts[key], str):
                        if rtopts[key] == ' ':
                            rtopts[key] = value
                        else:
                            rtopts[key] += ' ' + value
                    else:
                        logging.warning('unknown type')
                else:
                    rtopts[key] = value

        if override:
            rtopts.update(override)

        runtest.extend(reconstruct_rtcmd(rtargs, rtopts, canonical=canonical))
    else:

        runtest.append(dictionary.get('cmd', ''))


    rtcmd = ' '.join(runtest)


    if not slurm:
        return rtcmd


    for opt in runtest:
        if re.match(r'-host', opt):
            logging.warning("The runtest option '-host' does not control where the slurm job is run, use the runta '--nodelist' option instead.")
        


    sbatch = dictionary.get('sbatch', 'sbatch')




    if nodelist:
        sbatch = sbatch_add_arg(sbatch, '-w', nodelist)
    else:

        match = re.search(r'-w \{(.*)\}', sbatch)
        if match:
            hosts = match.group(1).split(',')
            host = random.choice(hosts)

            sbatch = sbatch.replace(match.group(1), match.group(1).replace(' ', ''))
            sbatch = sbatch_add_arg(sbatch, '-w', host)
        else:
            match = re.search(r'-w (\S+)', sbatch)
            if match:
                host = match.group(1)
            else:
                host = ''


    if test_only:
        sbatch = sbatch_add_arg(sbatch, '--test-only', None)


    if jobname:
        jobname = re.sub(r'%F', os.path.splitext(dictionary.get('file'))[0],
                         jobname)
        jobname = re.sub(r'%N', host, jobname)
        if partition:
            jobname = re.sub(r'%P', partition, jobname)
        jobname = re.sub(r'%u', os.getlogin(), jobname)
        jobname = re.sub(r'%U', rtopts.get('user', os.getlogin()), jobname)
        sbatch = sbatch_add_arg(sbatch, '-J', jobname)


    if partition:

        sbatch = sbatch_add_arg(sbatch, '--partition', partition,
                                override=force_partition)

    if time_hints:

        testcount = len(rtopts.get('test', []))

        suite = rtopts.get('suite')

        if testcount == 0:

            testcount = suite_count.get(suite, 1)
            testcount -= len(rtopts.get('rmtest', []))

        testcount = max(testcount, 1)


        (ctimeout, etimeout) = get_suite_timeout(suite)


        timehint = int(testcount * (int(rtopts.get('ctimeout', ctimeout)) +
                                    int(rtopts.get('etimeout', etimeout))) /
                       int(rtopts.get('threads', 1)))


        if rtopts.get('osversion') == 'Linux_aarch64':
            timehint *= 4


        timehint = int(timehint / 60) + 5
        
        sbatch = sbatch_add_arg(sbatch, '--time', timehint)


    sbatch = sbatch_add_arg(sbatch, '--export', 'HOME', equal=True)
    sbatch = sbatch_add_arg(sbatch, '--propagate', 'NONE', equal=True)


    sbatch = sbatch_add_arg(sbatch, '--wrap', '"__rtcmd__"')

    if not save_log:

        sbatch = sbatch_add_arg(sbatch, '-o', '/dev/null')
        sbatch = sbatch_add_arg(sbatch, '-e', '/dev/null')


    sbatch = sbatch.replace('__rtcmd__', rtcmd)

    return sbatch

def read_sched(cfg, check_host=True, slurm=True, strict=False):

    try:
        sched = Schedule(cfg, strict=strict)
    except Exception as e:
        logging.error(e)
        exit(1)

    out = []
    for section, cmds in sched.commands.iteritems():
        logging.debug(section)

        match = re.search(r'\|\s*(sbatch .*)', section)
        if match:
            sbatch = match.group(1).strip()
        elif slurm:
            logging.warning('Invalid section header: "{}"'.format(section))
            continue
        else:
            sbatch = ''

        for cmd in cmds:
            rtargs, rtopts = deconstruct_rtcmd(cmd)

            if check_host and rtopts.get('host'):
                logging.warning('-host flag used in schedule, skipping: "{}"'.format(section))
                continue

            d = {
                'section': section,
                'cmd': cmd,
                'rtargs': rtargs,
                'rtopts': rtopts,
                'sbatch': sbatch,
                'file': os.path.basename(cfg)
            }
            out.append(d)

    return out

def reconstruct_rtcmd(rtargs, rtopts, canonical=False):


    runtest = []

    def process_args(key, val):


        if isinstance(val, bool):
            return '-{0}'.format(key)
        else:
            if isinstance(val, list):
                if key in ['env', 'make']:
                    val = ' '.join(list(map(shlex_quote, val)))
                else:
                    val = ' '.join(val)
            else:
                if key in ['cflags', 'cxxflags', 'f', 'fflags', 'nvccf']:

                    val = '\'{0}\''.format(val)
                else:
                    pass

            return '-{0} {1}'.format(key, val)


    if canonical:

        order = ['version', 'compiler', 'user', 'osversion', 'suite', 'f',
                 'test']
        remainder = sorted([i for i in rtargs if i not in order])
        order.extend(remainder)
        rtargs = sorted(rtargs, key=lambda i: order.index(i))
    for key in rtargs:
        arg = process_args(key, rtopts.get(key))
        runtest.append(arg)


    for key in rtopts.keys():
        if key not in rtargs:
            arg = process_args(key, rtopts.get(key))
            runtest.append(arg)

    return runtest

def run_cmd(cmd, verbose=False):

    logging.debug(cmd)
            
    if verbose:
        out = ''
        p = subprocess.Popen(shlex.split(cmd), bufsize=1,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        while p.poll() is None:
            line = p.stdout.readline()

            out = out + line


            print(line, end='')

        p.wait()

        ret = p.returncode

        return out, '', ret
    else:
        p = subprocess.Popen(shlex.split(cmd),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        ret = p.returncode

        return stdout, stderr, ret

def main():
    proj_ta = os.environ.get('PROJ_TA')
    if proj_ta is None:
        logging.error('PROJ_TA environment variable is not set')
        exit(1)

    parser = argparse.ArgumentParser(description='runta script')
    parser.add_argument('schedule', nargs='*',
                        type=argparse.FileType('r'),
                        help='schedule file name')
    parser.add_argument('--add-timehints', action='store_true',
                        help='Add estimated job times to help Slurm')
    parser.add_argument('--append', action=KeyValue, metavar='key=value',
                        nargs='+', default={},
                        help='Append onto runtest parameters with specified key/value pair(s)')
    parser.add_argument('--canonical', default=False, action='store_true',
                        help='Sort runtest arguments in canonical order')
    parser.add_argument('-cflags',type=str, 
                        help='Filter on runtest -cflags (regex)')
    parser.add_argument('--check-reconstruct', action='store_true',
                        help=argparse.SUPPRESS)
    parser.add_argument('--compiler', '-compiler', type=str,
                        help='Filter on runtest -compiler')
    parser.add_argument('--config', type=argparse.FileType('r'),
                        default=os.path.join(proj_ta, 'etc', 'runta.yml'),
                         help='runta configuration file - not the schedule file')
    parser.add_argument('-cxxflags',type=str, 
                        help='Filter on runtest -cxxflags (regex)')
    parser.add_argument('--dryrun', '-n', '-dryrun', '-dryrun_for_generation',
                        action='store_true', default=False,
                        help='Do not run anything, just print the commands')
    parser.add_argument('-f', type=str, help='Filter on runtest -f (regex)')
    parser.add_argument('-fcflags',type=str, 
                        help='Filter on runtest -fcflags (regex)')
    parser.add_argument('--firstrun', default=False, action='store_true',
                        help='Pull the first instance of each suite to the top to be run first.  Best if used with --shuffle.')
    parser.add_argument('--firstrun-only', default=False, action='store_true',
                        help='Only run firstrun suites, ignore the residual suites')
    parser.add_argument('--force-partition', default=False,
                        action='store_true',
                        help='Set the Slurm partition to the specified value even if it is already defined by the schedule')
    parser.add_argument('--host', '-host', type=str,
                        help='Filter on Slurm host')
    parser.add_argument('--jobname', '-jobname', type=str,
                        help='Set the Slurm job name')
    parser.add_argument('--lint', default=False, action='store_true',
                        help='Run in lint mode')
    parser.add_argument('--minqa', default=False, action='store_true',
                        help='Enable minqa mode')
    parser.add_argument('--no-check-host-flag', dest='check_host',
                        action='store_false',
                        help='Do not check for the runtest -host flag')
    parser.add_argument('--nodelist', '-nodelist', type=str,
                        help='Set the node(s) on which to run the slurm job.')
    parser.add_argument('--no-slurm', dest='slurm', action='store_false',
                        help='Do not use Slurm, just plain old runtest')
    parser.add_argument('--osversion', '-osversion', type=str,
                        help='Filter on runtest -osversion')
    parser.add_argument('--override', action=KeyValue, metavar='key=value',
                        nargs='+', default={},
                        help='Override runtest parameters with specified key/value pair(s)')
    parser.add_argument('--partition', '--queue', '-queue', '-q', type=str,
                        help='Set the Slurm partition')
    parser.add_argument('--pgi', '-pgi', type=str,
                        help='Path to your sandbox when minqa mode is enabled')
    parser.add_argument('--save-log', '-s', '-save-log', default=False,
                        action='store_true',
                        help='Save the Slurm job log file')
    parser.add_argument('--shuffle', default=False, action='store_true',
                        help='Randomly shuffle the schedule')
    parser.add_argument('--strict', default=False, action='store_true',
                        help='Enable strict scheduling parsing mode')
    parser.add_argument('--suite', '-suite', type=str,
                        help='Filter on runtest -suite (regex)')
    parser.add_argument('--suitetype', type=str,
                        help='Filter on suitetype')
    parser.add_argument('--ta', type=str, action='append',
                        choices=['nvhpc-nightly-dev', 'nvhpc-nightly-rel',
                                 'nvhpc-weekly-dev', 'nvhpc-weekly-rel',
                                 'nvhpc_perf-nightly-dev',
                                 'nvhpc_perf-nightly-rel',
                                 'nvhpc_perf-nightly-baselines_dev',
                                 'nvhpc_perf-nightly-baselines_rel',
                                 'nvhpc_perf-nightly-comp',
                                 'nvhpc_perf-weekly-dev',
                                 'nvhpc_perf-weekly-rel',
                                 'nvhpc_perf-weekly-baselines_dev',
                                 'nvhpc_perf-weekly-baselines_rel',
                                 'nvhpc_perf-weekly-comp',
                                 'nghpc-nightly-dev', 'nghpc-nightly-rel',
                                 'nghpc-weekly-dev', 'nghpc-weekly-rel',
                                 'nghpc_perf-nightly-dev',
                                 'nghpc_perf-nightly-rel',                                 
                                 'grco-nightly-gcc', 'grco-nightly-llvm',
                                 'grco-weekly-gcc', 'grco-weekly-llvm'],
                        help='TA configuration to read from the config file, e.g., nvhpc-nightly-dev')
    parser.add_argument('--test-only', default=False, action='store_true',
                        help='Add Slurm option --test-only')
    parser.add_argument('--verbose', '-t',  default=False, action='store_true',
                        help='Print verbose output')
    parser.add_argument('--version', '-version', type=str,
                        help='Filter on runtest -version')
    parser.add_argument('--windows', default=False, action='store_true',
                        help='Generate Windows style commands')
    args = parser.parse_args()
    log_level = os.getenv('LOGLEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(level=log_level,
                        format='%(levelname)s: %(message)s')


    if not args.slurm:
        for opt in vars(args):
            if getattr(args, opt) and opt in ["add_timehints", "jobname", "nodelist", "partition", "save_log", "test_only"]:
                logging.error('--{} is incompatible with --no-slurm'.format(opt.replace('_','-')))
                exit(1)


    if args.schedule and args.ta:
        logging.error('--ta cannot be used with schedule file')
        exit(1)

    if args.suite and args.suitetype:
        logging.error('--suite and --suitetype are mutually exclusive')
        exit(1)
        
    if args.check_reconstruct and args.slurm is True:
        logging.info('Setting --no-slurm in order to use --check-reconstruct')
        args.slurm = False

    if args.firstrun_only and not args.firstrun:
        logging.info('Setting --firstrun in order to use --firstrun-only')
        args.firstrun = True

    if args.slurm is False and args.dryrun is False and args.verbose is False:
        logging.info('Setting --verbose in order to use --no-slurm')
        args.verbose = True

    if args.windows and args.slurm is True:
        logging.info('Setting --no-slurm in order to use --windows')
        args.slurm = False

    if args.minqa:

        if not args.pgi:
            logging.error('must specify --pgi')
            exit(1)


        args.force_partition = True
        args.jobname = 'minqa'
        if not args.partition:
            args.partition = 'correctness'

        d = {'pgi': args.pgi,
             'user': os.getlogin(),
             'version': 'mine',
             'xml': 'dev'}


        d.update(args.override)
        args.override = d


    suite_count = {}
    if args.add_timehints:
        suite_count = get_suite_count()

    cfgs = []
    if args.schedule:
        for c in args.schedule:
            cfgs.append(c.name)
    elif args.ta:
        yml = yaml.safe_load(args.config)
        for t in args.ta:
            ta = t.split('-')
            if len(ta) != 3:
                logging.error('Invalid ta string, must be a triplet')
                exit(1)
            cfgs.extend(yml.get(ta[0], {}).get(ta[1], {}).get(ta[2], []))

    if len(cfgs) == 0:
        logging.error('No schedule configuration file!')
        exit(1)


    sched = []
    for cfg in cfgs:
        logging.info('Reading {}'.format(cfg))
        out = read_sched(cfg, check_host=args.check_host, slurm=args.slurm,
                         strict=args.strict)
        logging.info('Read {} items'.format(len(out)))
        sched.extend(out)


    if args.compiler:
        sched = filter_sched(sched, 'compiler', args.compiler)

    if args.f:
        sched = filter_sched(sched, 'f', args.f, kind='regex')

    if args.cflags:
        sched = filter_sched(sched, 'cflags', args.cflags, kind='regex')

    if args.cxxflags:
        sched = filter_sched(sched, 'cxxflags', args.cxxflags, kind='regex')

    if args.fcflags:
        sched = filter_sched(sched, 'fcflags', args.fcflags, kind='regex')

    if args.host:
        sched = filter_sched(
            sched, 'sbatch',

            '(?:-w|--nodelist)(?:\s+|=)(?:\{{*){0}(?:\}}*)'.format(args.host),
            kind='slurm')

    if args.osversion:
        sched = filter_sched(sched, 'osversion', args.osversion)

    if args.suite:
        sched = filter_sched(sched, 'suite', args.suite, kind='regex')
    elif args.suitetype:

        suites = get_suites_by_type(args.suitetype)
        
        if not suites:
            logging.error('specified suitetype does not contain any suites')
            exit(1)
            

        sched = filter_sched(sched, 'suite', '|'.join(suites), kind='regex')

    if args.version:
        sched = filter_sched(sched, 'version', args.version)



    if len(sched) == 0:
        logging.error('No tests to schedule!')
        exit(1)


    if args.shuffle:
        random.shuffle(sched)


    if args.firstrun:
        sched = firstrun(sched, only=args.firstrun_only)


    count = {'success': 0, 'error': 0}
    for s in sched:
        cmdline = make_cmdline(s, append=args.append, canonical=args.canonical,
                               force_partition=args.force_partition,
                               jobname=args.jobname, nodelist=args.nodelist,
                               override=args.override, partition=args.partition, 
                               reconstruct=True, save_log=args.save_log, 
                               slurm=args.slurm, suite_count=suite_count,
                               test_only=args.test_only,
                               time_hints=args.add_timehints,
                               windows=args.windows)

        if args.check_reconstruct:
            orig = make_cmdline(s, reconstruct=False, slurm=args.slurm,
                                windows=args.windows)
            if cmdline != orig:
                logging.warning('DIFF:\n{0}\n{1}'.format(orig, cmdline))
        else:
            if args.dryrun:
                print(cmdline)
            elif args.lint:
                ret = lint(cmdline, s, strict=args.strict)
                count['error'] += ret
            else:
                logging.debug(cmdline)


                stdout, stderr, ret = run_cmd(cmdline, verbose=args.verbose)

                if args.slurm:
                    if args.test_only and ret != 0:
                        logging.error('Job cannot be submitted: {}'.format(cmdline))
                        count['error'] += 1
                    elif ret != 0:
                        logging.error('{0}: {1}'.format(stderr, cmdline))
                        count['error'] += 1
                    else:
                        logging.debug(stdout)
                        count['success'] += 1

    if args.lint:
        logging.info('{0} issues detected'.format(count['error']))
        if count['error'] != 0:
            exit(1)
    elif args.slurm and not args.dryrun:
        logging.info('{0} jobs successfully {2}, {1} errors'.format(
            count['success'], count['error'],
            'tested' if args.test_only else 'submitted'))

if __name__ == '__main__':
    main()
