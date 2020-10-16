#!/usr/bin/python3
import json
import configparser
import sys
import os
import tempfile
import glob
import subprocess
import shutil
import time

CONFIG_FILE_NAME = "xt-bundle-aos.cfg"

BUNDLE_CONFIG_SECTION = "bundle_config"
TOP_TEMPLATE = "top_template"
COMPONENTS = "components"
OPT_DEPLOY_DIR = "bundle_deploy_dir"
OPT_TYPE = "type"
OPT_ITEM_TEMPLATE = "item_template"
OPT_DEPENDENCIES = "dependencies"

SECT_PATH = "path"
OPT_BASE = "workspace_base_dir"

RUNTIME_DEPS = "runtimeDependencies"


class BundleProcessor:
    def __init__(self, cfg):
        print("BundleProcessor")
        self.__cfg = cfg

        #create bundle path
        self.__temp = tempfile.mkdtemp()
        print("Created temp dir for bundle, {}".format(self.__temp))

        top_template_path = cfg.get(BUNDLE_CONFIG_SECTION, TOP_TEMPLATE)
        with open(top_template_path) as top_template:
            self.__top_template = json.load(top_template)
            print("got top_template {}".format(str(self.__top_template)))
            for key, value in self.__top_template.items():
                if cfg.has_option(BUNDLE_CONFIG_SECTION, key):
                    self.__top_template[key] = cfg.get(
                        BUNDLE_CONFIG_SECTION, key)

            print("processed top_template {}".format(str(self.__top_template)))

        self.__components = list()
        self.__components_data = list()
        for component in cfg.get(BUNDLE_CONFIG_SECTION,
                                        COMPONENTS).split():
            print("component = {}".format(component))
            self.__components.append(component)
            self.__load_component(component)
        print("components = {}".format(self.__components))

        #Processing runtimeDependencies
        for comp in self.__components_data:
            comp[RUNTIME_DEPS] = self.__process_deps(comp['id'])

    def cleanup(self):
        shutil.rmtree(self.__temp, ignore_errors=True)

    def __process_deps(self, component):
        if self.__cfg.has_option(component, OPT_DEPENDENCIES) is not True:
            return {}

        deps = self.__cfg.get(component, OPT_DEPENDENCIES)
        deps_template = list()
        for dep in deps.split():
            print("got dep {}".format(dep))
            dep_list = dep.split("|")
            if dep_list[0] in self.__components:
                print("component enabled {}. Apply dep".format(dep_list[0]))
                item = {
                    "id":
                    dep_list[0],
                    "requiredVersion" if dep_list[1] == "r" else "minimalVersion":
                    dep_list[2]
                }
                deps_template.append(item)
        return deps_template

    def __load_component(self, component):
        with open(self.__cfg.get(component,
                                        OPT_ITEM_TEMPLATE)) as item_file:
            item_template = json.load(item_file)
            item_template['id'] = component
            keys_to_delete = list()
            print("got item template {}".format(str(item_template)))
            for key, value in item_template.items():
                if self.__cfg.has_option(component, key):
                    item_template[key] = self.__cfg.get(component, key)
                elif "optional" in value:
                    keys_to_delete.append(key)

            for key in keys_to_delete:
                del item_template[key]
            print("adding item template {}".format(str(item_template)))
            self.__components_data.append(item_template)

    def get_components(self):
        return self.__components

    def process_component(self, component, fileName, rootfs_type):
        print("process_component")
        for comp in self.__components_data:
            print("comp = {}".format(comp))
            print("id = {}, comp = {}".format(comp['id'], component))
            if comp['id'] == component:
                index = self.__components_data.index(comp)
                self.__components_data[index]['fileName'] = fileName
                if rootfs_type:
                    self.__components_data[index]['annotations'] = {
                        'type': rootfs_type
                    }

    def prepare_bundle(self):
        print("prepare_bundle")
        self.__top_template[COMPONENTS] = self.__components_data
        print("metadata.json {}".format(str(self.__top_template)))
        with open('{}/metadata.json'.format(self.__temp), 'w') as outfile:
            json.dump(self.__top_template, outfile)

    def get_bundlepath(self):
        return self.__temp

    def get_type(self, component):
        if self.__cfg.has_option(component, OPT_TYPE) is not True:
            return ""
        return self.__cfg.get(component, OPT_TYPE)

    def get_basedir(self):
        return self.__cfg.get(SECT_PATH, OPT_BASE)


OPT_OSTREE_PATH = "ostree_path"
OPT_OSTREE_BRANCH = "ostree_branch"
OSTREE_REPO_TYPE = "archive-z2"


class Ostree:
    def __init__(self, cfg, component):
        print("ostree init")
        self.__cfg = cfg
        self.__component = component
        self.__repo_path = cfg.get(component, OPT_OSTREE_PATH)
        self.__branch = self.__cfg.get(component, OPT_OSTREE_BRANCH)
        if not os.path.exists(self.__repo_path):
            print("Creating ostree repo")
            self.__create_ostree_repo(self.__repo_path)

    def __create_ostree_repo(self, repo_path):
        print("create ostree repo")
        os.mkdir(repo_path)
        os.system("ostree --repo={} init --mode={}".format(
            repo_path, OSTREE_REPO_TYPE))

    def pull_rootfs(self, ostree_rootfs):
        print("pull_rootfs")
        ostree_commit = subprocess.check_output(
            'ostree --repo={} rev-parse {}'.format(self.__repo_path,
                                                   self.__branch),
            shell=True, encoding='utf-8')
        ostree_commit = ostree_commit.replace('\n', ' ').replace('\r', '')
        if "status 1" in ostree_commit:
            raise Exception("no initial commit befor incremental")
        print('ostree commit = {}'.format(ostree_commit))
        os.system("ostree --repo={}/.ostree_repo init --mode=bare-user".format(
            ostree_rootfs))
        os.system("ostree --repo={}/.ostree_repo pull-local {} {}".format(
            ostree_rootfs, self.__repo_path, ostree_commit))
        os.system(
            "ostree --repo={}/.ostree_repo refs --create=aos_branch {}".format(
                ostree_rootfs, ostree_commit))
        os.system("ostree --repo={}/.ostree_repo checkout {}".format(
            ostree_rootfs, ostree_commit))

        #Removing ostree repo
        shutil.rmtree('{}/.ostree_repo'.format(ostree_rootfs))

    def commit_rootfs(self, rootfs_tar):
        print("commit rootfs")
        os.system(
            'ostree --repo={} commit --tree=tar={} --skip-if-unchanged --branch={} --subject="{}"'.
            format(self.__repo_path, rootfs_tar, self.__branch, component))


MKSDCARD_IMAGE_PATH = "meta-xt-prod-aos/doc"


class ImageBuilder:
    def __init__(self, cfg):
        print("image_builder")
        self.__cfg = cfg
        self.__temp = tempfile.mkdtemp()
        self.__mksdcard_path = os.path.join(
            self.__cfg.get(SECT_PATH, OPT_BASE), MKSDCARD_IMAGE_PATH)
        self.__loop_dev = ""

    def cleanup(self):
        if self.__loop_dev:
            os.system("sudo losetup -d {}".format(self.__loop_dev))
        shutil.rmtree(self.__temp, ignore_errors=True)

    def build_image(self, deploy_path):
        print("building image to {}".format(deploy_path))
        os.system("{}/mk_sdcard_image.sh -p {} -d {}/image.img -c aos".format(
            self.__mksdcard_path, deploy_path, self.__temp))

    def connect_image(self):
        print("connect image")
        self.__loop_dev = subprocess.check_output(
            "sudo losetup --find --partscan --show {}/image.img".format(
                self.__temp),
            shell=True, encoding='utf-8')
        print(self.__loop_dev)
        self.__loop_dev = self.__loop_dev.replace('\n', '').replace('\r', '')
        print("Got loop dev = {}".format(self.__loop_dev))

    def get_partition_device(self, partno):
        print("get part device {}".format(partno))
        if not self.__loop_dev:
            raise Exception("no loop device found")
        return "{}p{}".format(self.__loop_dev, partno)


DEPLOY_DIR = "build/deploy"
OPT_PARTITION_NO = "partition_no"
OPT_DOM_DEPLOY_DIR = "deploy_dir"


def get_full_rootfs(dom_update, item, bundle_path, cfg, image_builder):
    dom_update_gz = "{}.gz".format(dom_update)
    print("Getting rootfs for {}".format(item))
    dom_partition = cfg.get(item, OPT_PARTITION_NO)
    dom_dev = image_builder.get_partition_device(dom_partition)

    #TODO handle situation when user doesn't have sudo.
    os.system('sudo dd if={} of={}/{} bs=10M'.format(dom_dev, bundle_path,
                                                     dom_update))
    os.system('sudo gzip --fast -k {}/{}'.format(bundle_path, dom_update))
    os.system('sudo rm -rf {}'.format(os.path.join(bundle_path, dom_update)))

    return dom_update_gz


def build_rootfs(item, bundle_path, bundle_type, base_dir, cfg, image_builder):
    print("get_rootfs path = {} bundle_type = {}".format(
        bundle_path, bundle_type))

    deploy_dir = os.path.join(base_dir, DEPLOY_DIR)
    print("deploy_dir = {}".format(deploy_dir))
    component_root = ""
    search_item = cfg.get(item, OPT_DOM_DEPLOY_DIR)
    for name in os.listdir(deploy_dir):
        print("item {}".format(name))
        if search_item in name:
            component_root = name
            break

    print("found {}".format(component_root))
    if not component_root:
        raise Exception("component not found")

    component_dir = os.path.join(deploy_dir, component_root)
    print("component_dir = {}".format(component_dir))

    if item == "dom0":
        return get_full_rootfs("dom0_update", item, bundle_path, cfg,
                               image_builder)

    elif bundle_type:
        ostree = Ostree(cfg, item)
        rootfs = walk(component_dir, 'rootfs.tar.bz2')
        print('file {}'.format(rootfs))

        result = ""
        if bundle_type == 'incremental':
            print('process incremental image')
            raise Exception('Incrementals are not supported right now.')
            ostree_rootfs = os.path.join(bundle_path, "ostree_rootfs")
            new_rootfs = os.path.join(bundle_path, "new_rootfs")
            inc_rootfs = os.path.join(bundle_path, "inc_rootfs")
            os.mkdir(ostree_rootfs)
            os.mkdir(new_rootfs)
            os.mkdir(inc_rootfs)
            ostree.pull_rootfs(ostree_rootfs)
            os.system("tar xpf {} -C {}".format(rootfs, new_rootfs))
            os.chdir(inc_rootfs)
            #TODO handle rsync to work properly. Alt: use ostree to generate diff
            os.system(
                'rsync -HAXlrvcm --append --progress --delete --compare-dest={}/ {}/* .'.
                format(ostree_rootfs, new_rootfs))
            os.system('find . -type d -empty -delete')
            #TODO handle removed files

            os.chdir(inc_rootfs)
            #TODO make squashfs instead of tar archieve
            os.system('tar czf {}/{}_inc.tar.gz *'.format(bundle_path, item))
            force_remove(ostree_rootfs)
            force_remove(new_rootfs)
            force_remove(inc_rootfs)
            result = '{}_inc.tar.gz'.format(item)
        else:
            print('process full')
            return get_full_rootfs('{}_update'.format(item), item, bundle_path,
                                   cfg, image_builder)

        ostree.commit_rootfs(rootfs)
        return result

    raise Exception("unknown bundle type")


def force_remove(path):
    os.system('sudo rm -rf {}'.format(path))


def walk(filepath, template):
    for p, d, f in os.walk(filepath):
        for file in f:
            if file.endswith(template):
                return os.path.join(p, file)

    raise Exception("unable to find file or directory")


def main():
    try:
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_FILE_NAME)

        bundle = BundleProcessor(cfg)
        image_builder = ImageBuilder(cfg)

        image_builder.build_image(
            os.path.join(bundle.get_basedir(), DEPLOY_DIR))
        image_builder.connect_image()

        for component in bundle.get_components():
            print("got component {}".format(component))
            component_type = bundle.get_type(component)
            rootfs_file = build_rootfs(
                component, bundle.get_bundlepath(), component_type,
                bundle.get_basedir(), cfg, image_builder)
            bundle.process_component(component, rootfs_file, component_type)

        bundle.prepare_bundle()

        bundle_dir = cfg.get(BUNDLE_CONFIG_SECTION, OPT_DEPLOY_DIR)
        os.chdir(bundle.get_bundlepath())
        timestr = time.strftime("%Y%m%d-%H%M%S")
        os.system('tar czf {}/aos_bundle-{}.tar.gz *'.format(
            bundle_dir, timestr))
    except Exception as e:
        print(e)
        print("FAILED")
    finally:
        if ImageBuilder:
            image_builder.cleanup()
        if bundle:
            bundle.cleanup()


if __name__ == '__main__':
    main()
