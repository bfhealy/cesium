#!/usr/bin/python

from __future__ import print_function
from __future__ import unicode_literals
from __future__ import division
from __future__ import absolute_import
from builtins import open
from builtins import range
from builtins import dict
from builtins import str
from builtins import zip
from future import standard_library
standard_library.install_aliases()
from builtins import *
import glob
from parse import parse
from subprocess import call, Popen, PIPE
import sys
import os
import inspect
import pickle
import uuid
import shutil
from . import cfg
from . import lc_tools

class MissingRequiredParameterError(Exception):
    """Required parameter is not provided in feature function call."""

    def __init__(self,value):
        self.value = value

    def __str__(self):
        return str(self.value)


class MissingRequiredReturnKeyError(Exception):
    """Required return value is not provided in feature definition."""

    def __init__(self, value):
        """In"""
        self.value = value

    def __str__(self):
        return str(self.value)


class myFeature(object):
    """Decorator for custom-defined time series feature(s) function.

    Applies function wrapper that ensures required parameters and
    return values are present before executing, raising an exception if
    not.

    Attributes
    ----------
    requires : list
        List of names of features required for decorated function to
        execute.
    provides : list
        List of names of features generated by decorated function.

    """

    def __init__(self, requires, provides):
        """Instantiates object, sets args as attributes.

        Parameters
        ----------
        requires : list
            List of variable names required by the function.
        provides : list
            List of the key names of the returned dictionary - the
            features calculated by a particular function.

        """
        self.requires = requires
        self.provides = provides

    def __call__(self, f):
        """Wrap decorated function.

        Wrap decorated function with a check to ensure that required
        parameters (specified in decorator expression) are provided
        upon function call (raises MissingRequiredParameterError if
        not) and that all features reportedly returned (specified in
        decorator expression) are in fact returned (raises
        MissingRequiredReturnKeyError if not).

        Returns
        -------
        function
            The wrapped function.

        """
        def wrapped_f(*args, **kwargs):
            for required_arg in self.requires:
                if required_arg not in args and required_arg not in kwargs:
                    raise MissingRequiredParameterError(
                        "Required arg %s not provided in function call." %
                        required_arg)
            result_dict = f(*args, **kwargs)
            for provided in self.provides:
                if provided not in result_dict:
                    raise MissingRequiredReturnKeyError(
                        "Key %s not present in function return value." %
                        provided)
            return result_dict
        return wrapped_f


class DummyFile(object):
    """Used as a file object to temporarily redirect/suppress output."""
    def write(self, x):
        pass


def execute_functions_in_order(
        script_fpath,
        features_already_known={
            "t":[1,2,3], "m":[1,23,2], "e":[0.2,0.3,0.2], "coords":[22,33]},
        multiple_sources=False):
    """Generate custom features defined in script_fpath.

    Parses the script (which must have function definitions with
    decorators specifying the required parameters and those which are
    provided by each function) and executes the functions defined in
    that script such that all functions whose outputs are required
    as inputs of other functions are called first, if possible,
    otherwise raises an Exception.

    Parameters
    ----------
    script_fpath : str
        Path to custom feature definitions script.
    features_already_known : dict
        Dictionary providing all time-series data (time ("t"), magnitude
        ("m"), error ("e") as keys) and any meta-features.
        Example:
            {"t": [1, 2, 3], "m": [10.32, 11.41, 11.06],
             "e": [0.2015,0.3134,0.2953], "coords": [22.55,33.01]}

    Returns
    -------
    dict
        Dictionary of all extracted features (key-value pairs are
        feature name and feature value respectively).

    """
    # For when run inside Docker container:
    import sys
    import os
    try:
        with open(script_fpath) as f:
            all_lines = f.readlines()
    except IOError as e:
        raise(e)

    # import the custom feature defs
    from .custom_feature_scripts import custom_feature_defs

    fnames_req_prov_dict = {}
    all_required_params = []
    all_provided_params = []
    for i in range(len(all_lines)-1):
        if "@myFeature" in all_lines[i] and "def " in all_lines[i+1]:
            reqs_provs_1 = parse(
                "@myFeature(requires={requires}, provides={provides})",
                all_lines[i].strip())
            func_name = parse(
                "def {funcname}({args}):", all_lines[i+1].strip())
            fnames_req_prov_dict[func_name.named['funcname']] = {
                "requires": eval(reqs_provs_1.named["requires"]),
                "provides": eval(reqs_provs_1.named["provides"])}
            all_required_params = list(set(
                all_required_params +
                list(set(eval(reqs_provs_1.named["requires"])))))
            all_provided_params = list(set(
                all_provided_params +
                list(set(eval(reqs_provs_1.named["provides"])))))
    if type(features_already_known) == dict:
        features_already_known_list = [features_already_known]
    elif type(features_already_known) == list:
        features_already_known_list = features_already_known

    # temporarily redirect stdout:
    save_stdout = sys.stdout
    sys.stdout = DummyFile()
    all_extracted_features_list = []

    for features_already_known in features_already_known_list:
        all_required_params_copy = [x for x in all_required_params
                                    if x not in features_already_known]
        for reqd_param in all_required_params_copy:
            if reqd_param not in all_provided_params:
                raise Exception((
                    "Not all of the required parameters are provided by the "
                    "functions in this script (required parameter '%s').") %
                    str(reqd_param))
        funcs_round_1 = []
        func_queue = []
        funcnames = list(fnames_req_prov_dict.keys())
        i = 0
        func_rounds = {}
        all_extracted_features = {}

        while len(funcnames) > 0:
            func_rounds[str(i)] = []
            for funcname in funcnames:
                reqs_provs_dict = fnames_req_prov_dict[funcname]
                reqs = reqs_provs_dict['requires']
                provs = reqs_provs_dict['provides']
                if len(set(all_required_params_copy) & set(reqs)) > 0:
                    func_queue.append(funcname)
                else:
                    func_rounds[str(i)].append(funcname)
                    all_required_params_copy = [x for x in all_required_params_copy
                                           if x not in provs]
                    arguments = {}
                    for req in reqs:
                        if req in features_already_known:
                            arguments[req] = features_already_known[req]
                        elif req in all_extracted_features:
                            arguments[req] = all_extracted_features[req]
                    func_result = getattr(custom_feature_defs, funcname)(**arguments)
                    all_extracted_features = dict(
                        list(all_extracted_features.items()) + list(func_result.items()))
                    funcnames.remove(funcname)
            i += 1
        all_extracted_features_list.append(all_extracted_features)
    # revert to original stdout
    sys.stdout = save_stdout
    return all_extracted_features_list


def docker_installed():
    """Return boolean indicating whether Docker is installed."""
    from subprocess import call, PIPE
    try:
        x=call(["docker"], stdout=PIPE,stderr=PIPE)
        return True
    except OSError:
        return False


def docker_extract_features(
        script_fpath, features_already_known_list=[],
        ts_datafile_paths=None, ts_data_list=None):
    """Extract custom features in a Docker container.

    Spins up a docker container in which custom script
    excecution/feature extraction is done inside. Resulting data are
    copied to host machine and returned as a dict.

    Parameters
    ----------
    script_fpath : str
        Path to script containing custom feature definitions.
    features_already_known_list : list of dict, optional
        List of dictionaries containing time series data (t,m,e) and
        any meta-features to be used in generating custom features.
        Defaults to []. NOTE: If omitted, or if "t" or "m" are not
        among contained dict keys, either (a) respective element of
        `ts_datafile_paths` or (b) `ts_data_list` (see below) MUST not
        be None, otherwise raises ValueError.
    ts_datafile_paths : list of str, optional
        List of paths to time-series CSV files. Defaults to None. NOTE:
        If None, either (a) corresponding element of
        `features_already_known_list` (see above) must contain "t"
        (time) and "m" (magnitude, or the measurement at each time)
        among its keys, OR (b) `ts_data_list` (see below) must be
        provided, otherwise raises ValueError.
    ts_data_list : list of list OR str, optional
        List of either (a) list of lists/tuples each containing t,m(,e)
        for each epoch, or (b) string containing equivalent comma-
        separated lines, each line being separated by a newline
        character ("\n"). Defaults to None. NOTE: If None, either
        `ts_datafile_paths` must not be None or "t" (time) and "m"
        (magnitude/measurement) must be among the keys of
        respective element of `features_already_known_list` (see
        above), otherwise raisesValueError.

    Returns
    -------
    list of dict
        List of dictionaries of all generated features.

    """
    if isinstance(features_already_known_list, dict):
        features_already_known_list = [features_already_known_list]
    for features_already_known in features_already_known_list:
        if "t" not in features_already_known or "m" not in features_already_known:
            ## get ts data and put into features_already_known
            if ts_datafile_path is None and ts_data is None:
                raise ValueError("No time series data provided! ts_datafile_path "
                                 "is None and ts_data is None  !!")
            tme = []
            if ts_datafile_path: # path to ts data file
                # parse ts data and put t,m(,e) into features_already_known
                with open(ts_datafile_path) as f:
                    all_lines = f.readlines()
                for i in range(len(all_lines)):
                    if all_lines[i].strip() == "":
                        continue
                    else:
                        tme.append(all_lines[i].strip().split(","))
            else: # ts_data passed directly
                # parse ts data and put t,m(,e) into features_already_known
                if type(ts_data) == list:
                    if len(ts_data) > 0:
                        if (type(ts_data[0]) in [list, tuple]
                                and type(ts_data[0][0]) == float):
                            # ts_data already in desired format
                            tme = ts_data
                        elif type(ts_data[0]) == str and "," in ts_data[0]:
                            for el in ts_data:
                                if el not in ["\n",""]:
                                    tme.append(el.split(","))
                    else:
                        raise ValueError("ts_data is an empty list")
                elif type(ts_data) == str:
                    all_lines = ts_data.strip().split("\n")
                    for i in range(len(all_lines)):
                        if all_lines[i].strip() == "":
                            continue
                        else:
                            tme.append(all_lines[i].strip().split(","))
            if len(tme) > 0:
                if all(len(this_tme) == 3 for this_tme in tme):
                    T,M,E = list(zip(*tme))
                    T = [float(el) for el in T]
                    M = [float(el) for el in M]
                    E = [float(el) for el in E]
                    features_already_known["t"] = T
                    features_already_known["m"] = M
                    features_already_known["e"] = E
                elif all(len(this_tme) == 2 for this_tme in tme):
                    T,M = list(zip(*tme))
                    T = [float(el) for el in T]
                    M = [float(el) for el in M]
                    features_already_known["t"] = T
                    features_already_known["m"] = M
                else:
                    raise Exception("custom_feature_tools.py - "
                                    "docker_extract_features() - not all elements "
                                    "of tme are the same length.")
    container_name = str(uuid.uuid4())[:10]
    path_to_tmp_dir = os.path.join("/tmp", container_name)
    os.mkdir(path_to_tmp_dir)
    # copy custom features defs script and pickle the relevant
    # tsdata file into docker temp directory
    status_code = call([
        "cp", script_fpath,
        os.path.join(
            os.path.join(
                cfg.MLTSP_PACKAGE_PATH, "custom_feature_scripts"),
            "custom_feature_defs.py")])
    with open(
            os.path.join(
                os.path.join(
                    cfg.PROJECT_PATH, "copied_data_files"),
                "features_already_known_list.pkl"),
            "wb"
        ) as f:
        pickle.dump(features_already_known_list,f)
    try:
        # the command to run our docker container which
        # will automatically generate features:
        cmd = ["docker", "run",
                "-v", "%s:/home/mltsp" % cfg.PROJECT_PATH,
                "--name=%s" % container_name,
                "mltsp/extract_custom_feats"]
        # execute command
        process = Popen(cmd, stdout=PIPE, stderr=PIPE)
        # grab outputs
        stdout, stderr = process.communicate()
        print("\n\ndocker container stdout:\n\n", stdout, \
              "\n\ndocker container stderr:\n\n", stderr, "\n\n")
        # copy all necessary files produced in docker container to host
        cmd = [
            "docker", "cp",
            "%s:/tmp/results_list_of_dict.pkl" % container_name,
            path_to_tmp_dir]
        status_code = call(cmd, stdout=PIPE, stderr=PIPE)
        print("/tmp/results_list_of_dict.pkl", \
              "copied to host machine - status code %s" % str(status_code))
        # load results from copied .pkl file
        with open(os.path.join(
                    path_to_tmp_dir, "results_list_of_dict.pkl"),
                "rb") as f:
            results_list_of_dict = pickle.load(f)
    except:
        raise
    finally:
        # Delete used container
        cmd = ["docker", "rm", "-f", container_name]
        status_code = call(cmd)#, stdout=PIPE, stderr=PIPE)
        print("Docker container deleted.")
        # Remove tmp dir
        shutil.rmtree(path_to_tmp_dir,ignore_errors=True)
        try:
            os.remove(
                os.path.join(
                    os.path.join(
                        cfg.MLTSP_PACKAGE_PATH, "custom_feature_scripts"),
                    "custom_feature_defs.py"))
            os.remove(
                os.path.join(
                    os.path.join(
                        cfg.MLTSP_PACKAGE_PATH, "custom_feature_scripts"),
                    "custom_feature_defs.pyc"))
            os.remove(
                os.path.join(
                    os.path.join(
                        cfg.MLTSP_PACKAGE_PATH, "custom_feature_scripts"),
                    "__init__.pyc"))
        except Exception as e:
            print(e)
        try:
            os.remove(
                os.path.join(
                    os.path.join(
                        cfg.PROJECT_PATH, "copied_data_files"),
                    "features_already_known_list.pkl"))
        except Exception as e:
            print(e)

    return results_list_of_dict


def test_new_script(
        script_fpath,
        docker_container=False):
    """Test custom features script and return generated features.

    Performs test run on custom feature def script with trial time
    series data sets and returns list of dicts containing extracted
    features if successful, otherwise raises an exception.

    Parameters
    ----------
    script_fpath : str
        Path to custom feature definitions script.
    docker_container : bool, optional
        Boolean indicating whether function is being called from within
        a Docker container.

    Returns
    -------
    list of dict
        List of dictionaries of extracted features for each of the trial
        time-series data sets.

    """
    features_already_known_list = []
    all_fnames = False
    try:
        all_fnames = glob.glob(
            os.path.join(cfg.PROJECT_PATH, ".sample_lcs/dotastro_*.dat"))[:1]
    except:
        pass
    if (is_running_in_docker_container() and
            (not all_fnames or len(all_fnames) == 0) and False):
        try:
            all_fnames = glob.glob("/home/mltsp/.sample_lcs/dotastro_*.dat")[:1]
        except:
            all_fnames = False
    if not all_fnames or len(all_fnames) == 0:
        print("all_fnames:", all_fnames)
        raise Exception("No test lc files read in...")
    else:
        for fname in all_fnames:
            t,m,e = parse_csv_file(fname)
            features_already_known_list.append(
                {"t":t,"m":m,"e":e,"coords":[0,0]})
    features_already_known_list.append(
        {"t":[1,2,3],"m":[50,51,52],"e":[0.3,0.2,0.4],"coords":[-11,-55]})
    features_already_known_list.append(
        {"t":[1],"m":[50],"e":[0.3],"coords":2})
    all_extracted_features_list = []
    if docker_installed():
        print("Extracting features inside docker container...")
        all_extracted_features_list = docker_extract_features(
            script_fpath=script_fpath,
            features_already_known_list=features_already_known_list)
    else:
        print("Docker not installed - running custom features script could be "
              "unsafe. Skipping generation of custom features.")
    return all_extracted_features_list


def list_features_provided(script_fpath):
    """Parses script and returns a list of all features it provides.

    Parses decorator expression in custom feature definitions script,
    returning a list of all feature names generated by the various
    definitions in that script.

    Parameters
    ----------
    script_fpath : str
        Path to custom features definition script.

    Returns
    -------
    list of str
        List of feature names that the script will generate.

    """
    with open(script_fpath) as f:
        all_lines = f.readlines()
    fnames_req_prov_dict = {}
    all_required_params = []
    all_provided_params = []
    for i in range(len(all_lines)-1):
        if "@myFeature" in all_lines[i] and "def " in all_lines[i+1]:
            reqs_provs_1 = parse(
                "@myFeature(requires={requires}, provides={provides})",
                all_lines[i].strip())
            func_name = parse(
                "def {funcname}({args}):", all_lines[i+1].strip())
            fnames_req_prov_dict[func_name.named['funcname']] = {
                "requires": eval(reqs_provs_1.named["requires"]),
                "provides": eval(reqs_provs_1.named["provides"])}
            all_required_params = list(set(
                all_required_params +
                list(set(eval(reqs_provs_1.named["requires"])))))
            all_provided_params = list(set(
            all_provided_params +
            list(set(eval(reqs_provs_1.named["provides"])))))
    return all_provided_params


def parse_csv_file(fname,sep=',',skip_lines=0):
    """Parse 2- or 3-column CSV file and return a list of its columns.

    Parameters
    ----------
    fname : str
        Absolute path to the CSV file.
    sep : str, optional
        Delimiter in TS data file, defaults to ",".
    skip_lines : int, optional
        Number of leading lines to skip in file, defaults to 0.

    Returns
    -------
    list of list
        Two- or three-element list of lists of each of the columns. If
        `fname` is not a 2- or 3-column CSV file, returns list of three
        empty lists.

    """
    f = open(fname)
    linecount = 0
    t,m,e = [[],[],[]]
    for line in f:
        line = line.strip()
        if linecount >= skip_lines:
            if len(line.split(sep)) == 3:
                ti,mi,ei = line.split(sep)
                t.append(float(ti)); m.append(float(mi)); e.append(float(ei))
            elif len(line.split(sep)) == 2:
                ti,mi = line.split(sep)
                t.append(float(ti)); m.append(float(mi))
            else:
                linecount -= 1
        linecount += 1
    #print linecount-1, "lines of data successfully read."
    f.close()
    return [t,m,e]


def generate_custom_features(
        custom_script_path, path_to_csv=None, features_already_known=[],
        ts_data=None):
    """Generate custom features for provided TS data and script.

    Parameters
    ----------
    custom_script_path : str
        Path to custom features script.
    path_to_csv : str, optional
        Path to CSV file containing time-series data. Defaults to None.
        If None, ts_data (see below) must not be None, otherwise
        raises an Exception.
    features_already_known : list of dict, optional
        List of dicts containing any meta-features associated with
        provided time-series data. Defaults to [].
    ts_data : list OR tuple, optional
        List (or tuple) of lists (or tuples) containing time,
        measurement (and optionally associated error values) data.
        Defaults to None. If None, path_to_csv must not be None,
        otherwise raises an Exception.

    Returns
    -------
    list of dict
        List of dictionaries containing newly-generated features.

    """
    if path_to_csv not in [None,False]:
        t,m,e = parse_csv_file(path_to_csv)
    elif ts_data not in [None,False]:
        if len(ts_data[0]) == 3:
            t,m,e = list(zip(*ts_data))
        if len(ts_data[0]) == 2:
            t,m = list(zip(*ts_data))
    else:
        print("predict_class.predict:")
        print("path_to_csv:", path_to_csv)
        print("ts_data:", ts_data)
        raise Exception("Neither path_to_csv nor ts_data provided...")
    features_already_known['t'] = t
    features_already_known['m'] = m
    if e and len(e) == len(m):
        features_already_known['e'] = e
    if is_running_in_docker_container():
        all_new_features = execute_functions_in_order(
                features_already_known=features_already_known,
                script_fpath=custom_script_path)
    else:
        if docker_installed():
            print("Generating custom features inside docker container...")
            all_new_features = docker_extract_features(
                script_fpath=custom_script_path,
                features_already_known_list=features_already_known)
        else:
            print("Generating custom features WITHOUT docker container...")
            all_new_features = execute_functions_in_order(
                features_already_known=features_already_known,
                script_fpath=custom_script_path)
    return all_new_features


def is_running_in_docker_container():
    """Return bool indicating whether running in a Docker container."""
    import subprocess
    proc = subprocess.Popen(["cat","/proc/1/cgroup"],stdout=subprocess.PIPE)
    output = proc.stdout.read()
    print(output)
    if "/docker/" in str(output):
        in_docker_container=True
    else:
        in_docker_container=False
    return in_docker_container


if __name__ == "__main__":
    import subprocess
    import sys
    encoding = sys.stdout.encoding or 'utf-8'
    docker_container = is_running_in_docker_container()
    x = test_new_script(docker_container=docker_container)
    print((str(x).encode(encoding)))
    sys.stdout.write( str(x).encode(encoding) )
    if docker_container:
        pass
