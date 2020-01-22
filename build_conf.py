import argparse
import datetime
import os
import shutil

import ConfigParser

# define build script version file name: this is created
# in the deploy dir after successfull build
VERSION_FNAME = 'build-system-version_1.0'

'''
The directories used during the build:
1. Build dir - volatile storage where the build happens,
must be the fastest storge possible, e.g. SSD drive
2. Storage dir - non-volatile directory, used by the builds
and remains alive through the builds, usually HDD. Used for:
2.1. Downloads - stores downloads made by Yocto
2.2. Build artifacts
2.3. Xen-troops repositories used for builds
2.4. Holds sstate-cache
'''

TYPE_DAILY = "dailybuild"
TYPE_PUSH = "on_push"
TYPE_REQ = "on_request"
TYPE_RECONSTR = "reconstruct"

TYPE = [
    TYPE_DAILY,
    TYPE_PUSH,
    TYPE_REQ,
    TYPE_RECONSTR
]

BUILD_VERSIONS_FNAME = "build-versions.inc"
BUILD_METADATA_REFS_FNAME = "metadata-revs"

YOCTO_DEFAULT_TARGET = "xt-image"

CFG_SECTION_GIT = "git"
CFG_OPTION_XT_HISTORY = "xt_history_uri"
CFG_OPTION_XT_MANIFEST = "xt_manifest_uri"

CFG_SECTION_PATH = "path"
CFG_OPTION_WORKSPACE_DIR = "workspace_base_dir"
CFG_OPTION_STORAGE_DIR = "workspace_storage_base_dir"
CFG_OPTION_CACHE_DIR = "workspace_cache_base_dir"

CFG_SECTION_CONF = "local_conf"


class BuildConf(object):
    def get_dir_build(self):
        return self.__workspace_base_dir

    def get_dir_storage(self):
        return self.__workspace_storage_base_dir

    def get_dir_cache(self):
        return self.__workspace_cache_base_dir

    # URI of the git repo with build history
    def get_uri_xt_history(self):
        return self.__xt_history_uri

    def get_dir_xt_history(self):
        return os.path.join(self.get_dir_storage(), 'build-history')

    # URI of the git repo with build manifests
    def get_uri_xt_manifest(self):
        return self.__xt_manifest_uri

    def get_dir_xt_manifest(self):
        return os.path.join(self.get_dir_storage(), 'build-manifest')

    def get_dir_buildhistory_rel(self):
        return self.__buildhistory_rel_dir

    def get_dir_history_artifacts(self):
        return os.path.join(self.get_dir_xt_history(),
                            self.get_dir_buildhistory_rel())

    # this is the directory we deliver artifacts to
    def get_dir_build_artifacts(self):
        return os.path.join(self.get_dir_storage(), 'build-artifacts')

    def get_dir_yocto_downloads(self):
        return os.path.join(self.get_dir_storage(), 'downloads')

    # this is where we populate sstate-cache after the build,
    # so it can be used as SSTATE_MIRROR by others
    def get_dir_yocto_sstate_mirror(self):
        return os.path.join(self.get_dir_storage(), 'sstate-cache')

    def get_dir_yocto_sstate(self):
        return os.path.join(self.get_dir_cache(), 'current-build-cache')

    def get_dir_yocto_build(self):
        return os.path.join(self.get_dir_build(), 'build')

    def get_dir_yocto_deploy(self):
        return os.path.join(self.get_dir_yocto_build(), 'deploy')

    def get_dir_yocto_log(self):
        return os.path.join(self.get_dir_yocto_build(), 'log')

    def get_dir_yocto_buildhistory(self):
        return os.path.join(self.get_dir_yocto_build(), 'buildhistory')

    def get_dir_yocto_shared_rootfs(self):
        return os.path.join(self.get_dir_yocto_build(), 'shared_rootfs')

    # build options
    def get_opt_generate_local_conf(self):
        return self.__args.local_conf

    def get_opt_populate_sdk(self):
        return self.__args.populate_sdk

    def get_opt_populate_cache(self):
        return self.__args.populate_cache

    def get_opt_do_build(self):
        return self.__args.build_run

    def get_opt_buildhistory(self):
        return self.__args.buildhistory

    def get_opt_continue_build(self):
        return self.__args.continue_build

    def get_opt_build_type(self):
        return self.__args.build_type

    def get_opt_product_type(self):
        return 'prod-' + self.__args.product_type

    def get_opt_machine_type(self):
        return self.__args.machine_type

    def get_opt_parallel_build(self):
        return self.__args.parallel_build

    def get_opt_local_conf(self):
        return self.__xt_local_conf_options

    def get_opt_repo_branch(self):
        return self.__args.repo_branch

    def get_opt_reconstr_date(self):
        return self.__args.reconstr_date.strftime('%Y-%m-%d')

    def get_opt_reconstr_time(self):
        return self.__args.reconstr_time.strftime('%H-%M-%S')

    @staticmethod
    def setup_dir(path, remove=False, silent=False):
        # remove the existing one if any
        if remove:
            if not silent:
                print('Removing ' + path)
            try:
                shutil.rmtree(path)
            except OSError, err:
                if err.errno != os.errno.ENOENT:
                    raise
        try:
            os.makedirs(path)
        except OSError, err:
            if err.errno != os.errno.EEXIST:
                raise

    def __parse_args(self):
        parser = argparse.ArgumentParser()
        required = parser.add_argument_group('required arguments')
        required.add_argument('--build-type', choices=TYPE,
                              dest='build_type', required=True, help='Build type')
        required.add_argument('--machine',
                              dest='machine_type', required=True, help='Machine type')
        required.add_argument('--product',
                              dest='product_type', required=True, help='Product type')
        parser.add_argument('--with-local-conf', action='store_true',
                            dest='local_conf', required=False, default=False,
                            help='Generate local.conf for the build')
        parser.add_argument('--with-sdk', action='store_true',
                            dest='populate_sdk', required=False, default=False,
                            help='Populate SDK for the build')
        parser.add_argument('--with-populate-cache', action='store_true',
                            dest='populate_cache', required=False, default=False,
                            help='Populate build cache (sstate, ccache)')
        parser.add_argument('--with-do-build', action='store_true',
                            dest='build_run', required=False, default=False,
                            help='Also build after initialization')
        parser.add_argument('--with-build-history', action='store_true',
                            dest='buildhistory', required=False, default=False,
                            help='Save build history in the git repository')
        parser.add_argument('--continue-build', action='store_true',
                            dest='continue_build', required=False, default=False,
                            help='Continue existing build if any, do not clean up')
        parser.add_argument('--retain-sstate', action='store_true',
                            dest='retain_sstate', required=False, default=False,
                            help='Do not remove SSTATE_DIR at any circumstances')
        parser.add_argument('--parallel-build', action='store_true',
                            dest='parallel_build', required=False, default=False,
                            help='Allow parallel building of domains')
        parser.add_argument('--config',
                            dest='config_file', required=False,
                            help="Use configuration file for tuning")
        parser.add_argument('--branch',
                            dest='repo_branch', required=False,
                            default='master',
                            help="Use product's manifest from the branch specified")
        known_args, other_args = parser.parse_known_args()
        # now that we know which build it is we can add appropriate options
        if known_args.build_type == TYPE_RECONSTR:
            parser.add_argument('--date',
                                dest='reconstr_date', required=True,
                                help='Date of the build to reconstruct',
                                type=lambda d: datetime.datetime.strptime(d, '%Y-%m-%d'))
            parser.add_argument('--time',
                                dest='reconstr_time', required=True,
                                help='Time of the build to reconstruct',
                                type=lambda d: datetime.datetime.strptime(d, '%H-%M-%S'))
        self.__args = parser.parse_args()

    @staticmethod
    def expand_path(path):
        return os.path.normpath(os.path.expandvars(os.path.expanduser(path)))

    def set_work_config(self):
        # place where build happens, SSD
        self.__workspace_base_dir = os.path.join(os.sep, 'tmp', 'build-ssd')
        # place where we store files which can be re-used
        self.__workspace_storage_base_dir = os.path.join(os.sep, 'tmp', 'build-hdd')
        # place where we store Yocto's sstate and ccache
        self.__workspace_cache_base_dir = os.path.join(os.sep, 'tmp', 'build-ssd')

        # URI of the git repo with build history
        self.__xt_history_uri = 'ssh://git@git.epam.com/epmd-aepr/build-history.git'
        # URI of the git repo with build manifests
        self.__xt_manifest_uri = 'https://github.com/xen-troops/meta-xt-products.git'

        if self.__args.config_file:
            config = ConfigParser.ConfigParser()
            config.read(self.__args.config_file)
            uri = config.get(CFG_SECTION_PATH, CFG_OPTION_WORKSPACE_DIR, 1)
            if uri:
                self.__workspace_base_dir = BuildConf.expand_path(uri)
            uri = config.get(CFG_SECTION_PATH, CFG_OPTION_STORAGE_DIR, 1)
            if uri:
                self.__workspace_storage_base_dir = BuildConf.expand_path(uri)
            uri = config.get(CFG_SECTION_PATH, CFG_OPTION_CACHE_DIR, 1)
            if uri:
                self.__workspace_cache_base_dir = BuildConf.expand_path(uri)
            uri = config.get(CFG_SECTION_GIT, CFG_OPTION_XT_HISTORY, 1)
            if uri:
                self.__xt_history_uri = uri
            uri = config.get(CFG_SECTION_GIT, CFG_OPTION_XT_MANIFEST, 1)
            if uri:
                self.__xt_manifest_uri = uri
            self.__xt_local_conf_options = []
            try:
                config_items = config.items(CFG_SECTION_CONF)
                if config_items:
                    self.__xt_local_conf_options = config_items
            except ConfigParser.NoSectionError:
                pass

    def __init__(self):
        # get build arguments
        self.__parse_args()
        self.set_work_config()
        self.__buildhistory_rel_dir = os.path.join(self.get_opt_build_type(),
                                                   datetime.date.today().strftime('%Y-%m-%d'),
                                                   self.get_opt_product_type(), self.get_opt_machine_type(),
                                                   datetime.datetime.now().strftime('%H-%M-%S'))
        BuildConf.setup_dir(self.get_dir_build(), not self.__args.continue_build)
        BuildConf.setup_dir(self.get_dir_storage())
        BuildConf.setup_dir(self.get_dir_yocto_sstate(), not (self.__args.continue_build or self.__args.retain_sstate))
