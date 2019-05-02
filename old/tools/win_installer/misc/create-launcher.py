
"""Creates simple Python .exe launchers for gui and cli apps

./create-launcher.py "3.8.0" <target-dir>
"""

import os
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile


def build_resource(rc_path, out_path):
    """Raises subprocess.CalledProcessError"""

    def is_64bit():
        return struct.calcsize("P") == 8

    subprocess.check_call(
        ["windres", "-O", "coff", "-F",
         "pe-x86-64" if is_64bit() else "pe-i386", rc_path,
         "-o", out_path])


def get_build_args():
    python_name = os.path.splitext(os.path.basename(sys.executable))[0]
    python_config = os.path.join(
        os.path.dirname(sys.executable), python_name + "-config")

    cflags = subprocess.check_output(
        ["sh", python_config, "--cflags"]).strip()
    libs = subprocess.check_output(
        ["sh", python_config, "--libs"]).strip()

    cflags = os.fsdecode(cflags)
    libs = os.fsdecode(libs)
    return shlex.split(cflags) + shlex.split(libs)


def build_exe(source_path, resource_path, is_gui, out_path):
    args = ["gcc", "-s"]
    if is_gui:
        args.append("-mwindows")
    args.append("-municode")
    args.extend(["-o", out_path, source_path, resource_path])
    args.extend(get_build_args())
    print("Compiling launcher: %r", args)
    subprocess.check_call(args)


def get_launcher_code(entry_point):
    module, func = entry_point.split(":", 1)

    template = """\
#include "Python.h"
#include <windows.h>
#include <tchar.h>

#define BUFSIZE 32768

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                    PWSTR lpCmdLine, int nCmdShow)
{
    int result;

    DWORD retval = 0;
    BOOL success;
    WCHAR buffer[BUFSIZE] = {0};
    WCHAR* lppPart[1] = {NULL};

    retval = GetFullPathNameW(__wargv[0], BUFSIZE, buffer, lppPart);

    if (retval == 0)
    {
        // It's bad, but can be ignored
        printf ("GetFullPathName failed (%%d)\\n", GetLastError());
    }
    else if (retval < BUFSIZE)
    {
        if (lppPart != NULL && *lppPart != 0)
        {
            lppPart[0][-1] = 0;
            printf("Calling SetDllDirectoryW(%%ls)\\n", buffer);
            success = SetDllDirectoryW(buffer);
            if (success)
            {
                printf("Successfully SetDllDirectoryW\\n");
            }
            else
            {
                printf ("SetDllDirectoryW failed (%%d)\\n", GetLastError());
            }
        }
        else
        {
            printf ("E: GetFullPathName didn't return filename\\n");
        }
    }
    else
    {
        printf ("GetFullPathName buffer too small (required %%d)\\n", retval);
        return -1; // this shouldn't happen
    }

    Py_NoUserSiteDirectory = 1;
    Py_IgnoreEnvironmentFlag = 1;
    Py_DontWriteBytecodeFlag = 1;
    Py_Initialize();
    PySys_SetArgvEx(__argc, __wargv, 0);
    result = PyRun_SimpleString("%s");
    Py_Finalize();
    return result;
}
    """

    launch_code = "import sys; from %s import %s; sys.exit(%s())" % (
        module, func, func)
    return template % launch_code


def get_resource_code(filename, file_version, file_desc, icon_path,
                      product_name, product_version, company_name):

    template = """\
1 ICON "%(icon_path)s"
1 VERSIONINFO
FILEVERSION     %(file_version_list)s
PRODUCTVERSION  %(product_version_list)s
FILEOS 0x4
FILETYPE 0x1
BEGIN
    BLOCK "StringFileInfo"
    BEGIN
        BLOCK "040904E4"
        BEGIN
            VALUE "CompanyName",      "%(company_name)s"
            VALUE "FileDescription",  "%(file_desc)s"
            VALUE "FileVersion",      "%(file_version)s"
            VALUE "InternalName",     "%(internal_name)s"
            VALUE "OriginalFilename", "%(filename)s"
            VALUE "ProductName",      "%(product_name)s"
            VALUE "ProductVersion",   "%(product_version)s"
        END
    END
    BLOCK "VarFileInfo"
    BEGIN
        VALUE "Translation", 0x409, 1252
    END
END
"""

    def to_ver_list(v):
        return ",".join(map(str, (list(map(int, v.split("."))) + [0] * 4)[:4]))

    file_version_list = to_ver_list(file_version)
    product_version_list = to_ver_list(product_version)

    return template % {
        "icon_path": icon_path, "file_version_list": file_version_list,
        "product_version_list": product_version_list,
        "file_version": file_version, "product_version": product_version,
        "company_name": company_name, "filename": filename,
        "internal_name": os.path.splitext(filename)[0],
        "product_name": product_name, "file_desc": file_desc,
    }


def main():
    argv = sys.argv

    version = argv[1]
    target = argv[2]

    company_name = "The gPodder Team"
    misc = os.path.dirname(os.path.realpath(__file__))

if __name__ == "__main__":
    main()
