import git
import os
import shutil
import subprocess
from github import Github
import build_conf
import re

def list_directories(path):
    dirnames = [files for files in os.listdir(path) if os.path.isdir(os.path.join(path, files))]
    if '.git' in dirnames:
        dirnames.remove('.git')
    return dirnames


def list_xml_files(path):
    return [files for files in os.listdir(path) if files.endswith(".xml")]


def copy_file(src, dst, fname):
    src = os.path.join(src, fname)
    dst = os.path.join(dst, fname)
    try:
        os.remove(dst)
    except OSError, err:
        if err.errno != os.errno.ENOENT:
            raise
    try:
        # copy with file stats
        shutil.copy2(src, dst)
    except IOError, err:
        if err.errno != os.errno.ENOENT:
            raise


def copy_dir(src, dst):
    try:
        shutil.rmtree(dst)
    except OSError, err:
        if err.errno != os.errno.ENOENT:
            raise
    try:
        shutil.copytree(src, dst, True)
    except OSError, err:
        if err.errno != os.errno.ENOENT:
            raise


def bash_run_command(cmd):
    ret = subprocess.call("bash -c '%s'" % cmd, shell=True)
    if ret != 0:
        raise Exception('Failed to run "' + cmd + '", error code: ' + str(ret))

# block to work with pull requests

def verify_pulls(existed, proposed, uri):
    print('Verifying of the proposed pulls: {}'.format(proposed))
    for pr in proposed:
         print('Verifying {}'.format(pr))
         if not pr in existed:
             print('Pull request {} does not exist in {} repository.'.format(pr, uri))
             return False
    return True


def get_pulls_for(uri):
    print('Getting the pulls for {}'.format(uri))
    g = Github()
    repo = g.get_repo(uri)
    pulls = repo.get_pulls(state='open', sort='created', base='master')
    res = []
    for pr in pulls:
        res.append(pr.number)
    return res

def handle_pulls_input(inputstr):
    inputstr = ''.join(inputstr.split())
    return list(map(int, inputstr.split(",")))


def apply_pulls(proposed):
    for pull in proposed:
        print('Applying pull request {}'.format(pull))
        bash_run_command('git pull pull_req_source pull/%s/head --rebase' % (pull))


def process_pulls(uri, proposed):
    proposed = handle_pulls_input(proposed)
    existed = get_pulls_for(uri)
    if verify_pulls(existed, proposed, uri):
        apply_pulls(proposed)
        return True

    return False

# end of pull requests block

def git_init(dir, uri):
    print('Cloning from ' + uri)
    build_conf.BuildConf.setup_dir(dir, remove=True, silent=True)
    git.Repo.clone_from(uri, dir, branch='master')


def git_commit(cfg, dir):
    repo = git.Repo(dir)
    repo.heads.master.checkout()
    repo.git.add('.')
    repo.git.commit(m=cfg.get_dir_buildhistory_rel())
    repo.remotes.origin.push()


def buildhistory_init(cfg):
    if not cfg.get_opt_buildhistory():
        print('Not using build history')
        return
    print('Initializing build history git repository')
    git_init(cfg.get_dir_xt_history(), cfg.get_uri_xt_history())


def buildhistory_commit(cfg):
    if not cfg.get_opt_buildhistory():
        return
    print('Commititng build history')
    git_commit(cfg, cfg.get_dir_xt_history())


def repo_init(uri, branch, xml_base_name):
    bash_run_command('repo init -u %s -b %s -m %s.xml' %
                     (uri, branch, xml_base_name))


def repo_sync():
    bash_run_command('repo sync -j8')


def repo_populate_manifest_get_fname(cfg):
    return cfg.get_opt_product_type() + '.xml'


def repo_populate_manifest(cfg):
    if not cfg.get_opt_buildhistory():
        return
    # setup build path variables
    history_artifacts_abs_dir = cfg.get_dir_history_artifacts()
    print('Saving current manifest to ' + history_artifacts_abs_dir)
    if not os.path.exists(history_artifacts_abs_dir):
        os.makedirs(history_artifacts_abs_dir)
    bash_run_command('repo manifest -r -o ' +
                     os.path.join(history_artifacts_abs_dir,
                                  repo_populate_manifest_get_fname(cfg)))


def yocto_run_command(cmd):
    src = os.path.join('xt-distro', 'oe-init-build-env')
    if cmd == '':
        bash_run_command('source ' + src)
    else:
        bash_run_command('source ' + src + ' && ' + cmd)


def yocto_add_bblayer(cfg, layer):
    yocto_run_command('bitbake-layers add-layer ' + os.path.join('..', layer))


def build_populate_artifacts(cfg):
    dest = os.path.join(cfg.get_dir_build_artifacts(),
                        cfg.get_dir_buildhistory_rel())
    print('Populating build artifacts to ' + dest)
    cfg.setup_dir(dest, remove=True, silent=True)
    # touch version file
    os.close(os.open(os.path.join(dest, build_conf.VERSION_FNAME),
                     os.O_CREAT | os.O_TRUNC))
    # images and sdk
    base_dir = cfg.get_dir_yocto_deploy()
    print("Populating images and SDK's")
    images_list = list_directories(base_dir)
    for image in images_list:
        print('\tFound ' + image)
        artifact_list = list_directories(os.path.join(base_dir, image))
        for artifact in artifact_list:
            if artifact in ['images', 'sdk']:
                if artifact == "sdk" and not cfg.get_opt_populate_sdk():
                    continue
                src = os.path.join(base_dir, image, artifact)
                dst = os.path.join(dest, image, artifact)
                print('\t\tPopulating ' + artifact)
                copy_dir(src, dst)
    # buildhistory
    base_dir = cfg.get_dir_yocto_buildhistory()
    print('Populating build history')
    # touch version file
    os.close(os.open(os.path.join(base_dir, build_conf.VERSION_FNAME),
                     os.O_CREAT | os.O_TRUNC))
    images_list = list_directories(base_dir)
    for image in images_list:
        print('\tFound ' + image)
        # copy to build artifacts
        src = os.path.join(base_dir, image)
        dst = os.path.join(dest, image)
        copy_file(src, dst, build_conf.BUILD_VERSIONS_FNAME)
        copy_file(src, dst, build_conf.BUILD_METADATA_REFS_FNAME)
        xml_list = list_xml_files(src)
        for xml in xml_list:
            copy_file(src, dst, xml)
        # copy to buildhistory git repo
        dst = os.path.join(cfg.get_dir_history_artifacts(), image)
        cfg.setup_dir(dst, remove=True, silent=True)
        copy_file(src, dst, build_conf.BUILD_VERSIONS_FNAME)
        copy_file(src, dst, build_conf.BUILD_METADATA_REFS_FNAME)
        for xml in xml_list:
            copy_file(src, dst, xml)
    # logs
    print('Populating logs')
    copy_dir(cfg.get_dir_yocto_log(), os.path.join(dest, 'logs'))
    # manifest
    print('Populating ' + repo_populate_manifest_get_fname(cfg))
    copy_file(cfg.get_dir_history_artifacts(), dest,
              repo_populate_manifest_get_fname(cfg))


def generate_local_conf(cfg, reconstruct_dir):
        print('Generating local.conf')
        f = open(os.path.join('build', 'conf', 'local.conf'), "w+t")
        # find the prod local conf
        local_conf = cfg.get_dir_build() + '//meta-xt-{}//doc//local.conf.{}'.format(cfg.get_opt_product_type(), cfg.get_opt_product_type())

        if os.path.isfile(local_conf):
            prod_file = open(local_conf, 'r')
            f.write(prod_file.read())
            prod_file.close()

        f.write('MACHINE = "' + cfg.get_opt_machine_type() + '"\n')
        if not cfg.get_opt_parallel_build():
            f.write('BB_NUMBER_THREADS = "1"\n')
        f.write('DL_DIR = "' + cfg.get_dir_yocto_downloads() + '"\n')
        f.write('DEPLOY_DIR = "' + cfg.get_dir_yocto_deploy() + '"\n')
        f.write('BUILDHISTORY_DIR = "' + cfg.get_dir_yocto_buildhistory() + '"\n')
        f.write('BUILDHISTORY_COMMIT = "1"\n')
        f.write('SSTATE_DIR = "' + cfg.get_dir_yocto_sstate() + '"\n')
        f.write('XT_SSTATE_CACHE_MIRROR_DIR = "' + cfg.get_dir_yocto_sstate_mirror() + '"\n')
        if cfg.get_opt_populate_cache():
            f.write('XT_POPULATE_SSTATE_CACHE = "1"\n')
        f.write('XT_SHARED_ROOTFS_DIR = "' + cfg.get_dir_yocto_shared_rootfs() + '"\n')
        if cfg.get_opt_populate_sdk():
            f.write('XT_POPULATE_SDK = "1"\n')
        f.write('LOG_DIR = "' + cfg.get_dir_yocto_log() + '"\n')
        f.write('XT_PRODUCT_NAME = "' + cfg.get_opt_product_type() +'"\n')
        if reconstruct_dir:
            f.write('XT_RECONSTRUCT_DIR = "' + reconstruct_dir + '"\n')

        if cfg.get_opt_local_conf():
            for item in cfg.get_opt_local_conf():
                if item[1]:
                    # Try expanding the argument if it uses environment vars
                    # This also works for non-path arguments
                    f.write(item[0].upper() + ' = ' +
                            cfg.expand_path(item[1]) + '\n')
                else:
                    f.write(item[0].upper() + ' = ""\n')
        f.close()


def add_meta_layers(cfg):
    bblayers_list = list_directories(cfg.get_dir_build())
    for bblayer in bblayers_list:
        if bblayer.startswith('meta-'):
            yocto_add_bblayer(cfg, bblayer)


def build_init(uri, branch, xml_base_name, proposed):
    if not branch:
        branch = 'master'

    repo_init(uri, branch, xml_base_name)
    repo_sync()
    if proposed:
        print('Applying pull requests: %s ...' % proposed)
        c_dir = os.getcwd()
        # go into prod layer directory to get the repo instance
        # and create the remote.
        # (It is required to apply the pull request).
        os.chdir('meta-xt-{}'.format(xml_base_name))
        # Get url of prod-layer to find the pull requests
        # The name of repository is known but organization - not
        # The organization can be extracted from the url of layer 'meta-xt-products'
        # Assumption:the layers  products and prod belong
        # to the same organization
        url = "xen-troops/meta-xt-" + xml_base_name
        repo = git.Repo('./')
        repo.create_remote('pull_req_source', url='git://github.com/{}'.format(url))
        # checkout the required branch
        repo.git.checkout('HEAD', b='{}'.format(branch))
        process_pulls(url, proposed)
        # rollback the current directory
        os.chdir(c_dir)
    # create build dir and make initial setup
    yocto_run_command('')


def build_run(cfg):
    buildhistory_init(cfg)
    bb_target = build_conf.YOCTO_DEFAULT_TARGET
    if cfg.get_opt_generate_update():
        bb_target = build_conf.YOCTO_UPDATE_TARGET
    
    # repo init + sync
    os.chdir(cfg.get_dir_build())
    if not (cfg.get_opt_continue_build() or cfg.get_opt_generate_update()):
        build_init(cfg.get_uri_xt_manifest(),
                cfg.get_opt_repo_branch(),
                cfg.get_opt_product_type(),
                cfg.get_prod_pulls())
        if cfg.get_opt_generate_local_conf():
            generate_local_conf(cfg, "")
        # add meta layers
        add_meta_layers(cfg)

    if not (cfg.get_opt_do_build() or cfg.get_opt_continue_build() or cfg.get_opt_generate_update()):
        return

    print('Building bitbake target: ' + bb_target)

    # ready for the build
    yocto_run_command('bitbake ' + bb_target)
    repo_populate_manifest(cfg)
    build_populate_artifacts(cfg)
    buildhistory_commit(cfg)


def build_print_target(build_type, cfg):
    print('Type: %s product: %s machine: %s' % (build_type,
                                                cfg.get_opt_product_type(), cfg.get_opt_machine_type()))


def build_daily(cfg):
    build_print_target(build_conf.TYPE_DAILY, cfg)
    build_run(cfg)


def build_push(cfg):
    build_print_target(build_conf.TYPE_PUSH, cfg)


def build_req(cfg):
    build_print_target(build_conf.TYPE_REQ, cfg)


def build_reconstr(cfg):
    build_print_target(build_conf.TYPE_RECONSTR, cfg)
    bb_target = build_conf.YOCTO_DEFAULT_TARGET
    os.chdir(cfg.get_dir_build())

    # construct path to the build history artifacts in the build history repo
    db_path = os.path.join('dailybuild', cfg.get_opt_reconstr_date(),
                                 cfg.get_opt_product_type(),
                                 cfg.get_opt_machine_type(),
                                 cfg.get_opt_reconstr_time())
    manifest_file = os.path.join(db_path, cfg.get_opt_product_type())
    if not cfg.get_opt_continue_build():
        build_init(cfg.get_uri_xt_history(), cfg.get_opt_repo_branch(),
                manifest_file)
        # point the upper Yocto to the folder which contains build history
        # artifacts
        history_path = os.path.join(cfg.get_dir_build(),'.repo', 'manifests',
                db_path)
        generate_local_conf(cfg, history_path)
        # add meta layers
        add_meta_layers(cfg)

    if not (cfg.get_opt_do_build() or cfg.get_opt_continue_build()):
        return
    # ready for the build
    yocto_run_command('bitbake ' + bb_target)
    build_populate_artifacts(cfg)


def main():
    try:
        cfg = build_conf.BuildConf()
        action = {
            build_conf.TYPE_DAILY: build_daily,
            build_conf.TYPE_PUSH: build_push,
            build_conf.TYPE_REQ: build_req,
            build_conf.TYPE_RECONSTR: build_reconstr,
        }
        action[cfg.get_opt_build_type()](cfg)
        print("Done")
    except Exception as e:
        print e
        print "FAILED"


if __name__ == '__main__':
    main()
