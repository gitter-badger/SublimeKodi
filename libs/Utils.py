import os
from lxml import etree as ET
import base64
import json
import colorsys
import codecs
from polib import polib
from urllib.request import Request, urlopen
import zipfile
import subprocess
import re
import platform
from threading import Thread
from functools import wraps
import time


def retry(ExceptionToCheck, tries=4, delay=3, backoff=2, logger=None):
    """Retry calling the decorated function using an exponential backoff.

    http://www.saltycrane.com/blog/2009/11/trying-out-retry-decorator-python/
    original from: http://wiki.python.org/moin/PythonDecoratorLibrary#Retry

    :param ExceptionToCheck: the exception to check. may be a tuple of
        exceptions to check
    :type ExceptionToCheck: Exception or tuple
    :param tries: number of times to try (not retry) before giving up
    :type tries: int
    :param delay: initial delay between retries in seconds
    :type delay: int
    :param backoff: backoff multiplier e.g. value of 2 will double the delay
        each retry
    :type backoff: int
    :param logger: logger to use. If None, print
    :type logger: logging.Logger instance
    """
    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    msg = "%s, Retrying in %d seconds..." % (str(e), mdelay)
                    if logger:
                        logger.warning(msg)
                    else:
                        log(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry

    return deco_retry


def run_async(func):
    @wraps(func)
    def async_func(*args, **kwargs):
        func_hl = Thread(target=func, args=args, kwargs=kwargs)
        func_hl.start()
        return func_hl

    return async_func


def check_busy(func):
    def decorator(self, *args, **kwargs):
        if self.is_busy:
            message_dialog("Already busy. Please wait.")
            return None
        self.is_busy = True
        try:
            func(self, *args, **kwargs)
        except Exception as e:
            message_dialog(e)
        self.is_busy = False
    return decorator


def get_sublime_path():
    if platform.system() == 'Darwin':
        return "subl"
    elif platform.system() == 'Linux':
        return "subl"
    elif os.path.exists(os.path.join(os.getcwd(), "sublime_text.exe")):
        return os.path.join(os.getcwd(), "sublime_text.exe")


def absoluteFilePaths(directory):
    for dirpath, _, filenames in os.walk(directory):
        for f in filenames:
            yield os.path.abspath(os.path.join(dirpath, f))


def make_archive(folderpath, archive):
    fileList = absoluteFilePaths(folderpath)
    a = zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED)
    for f in fileList:
        path_list = re.split(r'[\\/]', f)
        rel_path = os.path.relpath(f, folderpath)
        if ".git" in path_list:
            continue
        if rel_path.startswith("media") and not rel_path.endswith(".xbt"):
            continue
        if rel_path.startswith("themes"):
            continue
        if f.endswith(('.pyc', '.pyo', '.zip')):
            continue
        a.write(f, rel_path)
        yield rel_path
    a.close()


def tohex(r, g, b, a=None):
    if a is None:
        a = 255
    return "#%02X%02X%02X%02X" % (r, g, b, a)


def get_cont_col(col):
    (h, l, s) = colorsys.rgb_to_hls(int(col[1:3], 16)/255.0, int(col[3:5], 16)/255.0, int(col[5:7], 16)/255.0)
    l1 = 1 - l
    if abs(l1 - l) < .15:
        l1 = .15
    (r, g, b) = colorsys.hls_to_rgb(h, l1, s)
    return tohex(int(r * 255), int(g * 255), int(b * 255))  # true complementary


def check_bom(filename):
    file_bytes = min(32, os.path.getsize(filename))
    raw = open(filename, 'rb').read(file_bytes)
    return raw.startswith(codecs.BOM_UTF8)


def checkPaths(paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return ""


def texturepacker_generator(skin_path, settings):
    media_path = os.path.join(skin_path, "media")
    tp_path = settings.get("texturechecker_path")
    if tp_path:
        if platform.system() == "Linux":
            args = ['%s -dupecheck -input "%s" -output "%s"' % (tp_path, media_path, os.path.join(media_path, "Textures.xbt"))]
        else:
            args = [tp_path, '-dupecheck', '-input "%s"' % media_path, '-output "%s"' % os.path.join(media_path, "Textures.xbt")]
        with subprocess.Popen(args, stdout=subprocess.PIPE, bufsize=1, universal_newlines=True, shell=True) as p:
            for line in p.stdout:
                yield line


def check_brackets(str):
    stack = []
    pushChars, popChars = "<({[", ">)}]"
    for c in str:
        if c in pushChars:
            stack.append(c)
        elif c in popChars:
            if not len(stack):
                return False
            else:
                stackTop = stack.pop()
                balancingBracket = pushChars[popChars.index(c)]
                if stackTop != balancingBracket:
                    return False
    return not len(stack)


def findWord(view):
    for region in view.sel():
        if region.begin() == region.end():
            word = view.word(region)
        else:
            word = region
        if not word.empty():
            return view.substr(word)
        else:
            return ""


def get_node_content(view, flags):
    for region in view.sel():
        try:
            bracket_region = view.expand_by_class(region, flags, '<>"[]')
            return view.substr(bracket_region)
        except:
            return ""


def jump_to_label_declaration(view, label_id):
    view.run_command("insert", {"characters": label_id})
    view.hide_popup()


def log(string):
    print("SublimeKodi: " + str(string))


def message_dialog(string):
    try:
        import sublime
        sublime.message_dialog(string)
    except:
        log(string)


def yesno_dialog(string, ok_button):
    try:
        import sublime
        return sublime.ok_cancel_dialog(string, ok_button)
    except:
        log(string)
        return False


def get_tags_from_file(path, node_tags):
    nodes = []
    if not os.path.exists(path):
        log("%s does not exist" % path)
        return []
    root = get_root_from_file(path)
    if root is None:
        return []
    xpath = ".//" + " | .//".join(node_tags)
    for node in root.xpath(xpath):
        if "name" in node.attrib:
            if node.find("./param") is not None:
                continue
            include = {"name": node.attrib["name"],
                       "file": path,
                       "type": node.tag,
                       "content": ET.tostring(node, pretty_print=True, encoding="unicode"),
                       "line": node.sourceline}
            if node.getnext() is not None:
                include["length"] = node.getnext().sourceline - node.sourceline
            nodes.append(include)
    return nodes


def get_label_list(po_file_path):
    listitems = []
    try:
        po_file_content = codecs.open(po_file_path, "r", "utf-8").read()
        po = polib.pofile(po_file_content)
        for entry in po:
            string = {"id": entry.msgctxt,
                      "line": entry.linenum,
                      "comment": entry.comment,
                      "tcomment": entry.tcomment,
                      "string": entry.msgid,
                      "file": po_file_path,
                      "native_string": entry.msgstr}
            listitems.append(string)
        return listitems
    except Exception as e:
        answer = yesno_dialog("Error in %s:\n %s" % (po_file_path, str(e)), "Open")
        if answer:
            import sublime
            line = re.search(r"\(line ([0-9]+?)\)", str(e))
            if line:
                sublime.active_window().open_file("%s:%s" % (po_file_path, int(line.group(1))), sublime.ENCODED_POSITION)
            else:
                sublime.active_window().open_file(po_file_path)
        return []


def get_root_from_file(xml_file):
    try:
        parser = ET.XMLParser(remove_blank_text=True, remove_comments=True)
        tree = ET.parse(xml_file, parser)
        return tree.getroot()
    except Exception as e:
        # log("Error when parsing %s\n%s\nTry again with recover=True..." % (xml_file, e))
        # try:
        #     parser = ET.XMLParser(remove_blank_text=True, recover=True, remove_comments=True)
        #     tree = ET.parse(xml_file, parser)
        #     return tree.getroot()
        # except Exception as e:
        answer = yesno_dialog("Error in %s:\n %s" % (xml_file, str(e)), "Open")
        if answer:
            import sublime
            line = re.search(r"\(line ([0-9]+?)\)", str(e))
            if line:
                sublime.active_window().open_file("%s:%s" % (xml_file, int(line.group(1))), sublime.ENCODED_POSITION)
            else:
                sublime.active_window().open_file(xml_file)
        return None


def get_xml_file_paths(xml_path):
    xml_files = []
    if os.path.exists(xml_path):
            for xml_file in os.listdir(xml_path):
                filename = os.path.basename(xml_file)
                if filename.endswith(".xml"):
                    if filename.lower() not in ["script-skinshortcuts-includes.xml", "font.xml"]:
                        xml_files.append(xml_file)
            return xml_files
    else:
        return []


@run_async
def send_json_request_async(data, settings):
    return send_json_request(data, settings)


def send_json_request(data, settings):
    address = settings.get("kodi_address", "http://localhost:8080")
    if not address:
        return None
    credentials = '%s:%s' % (settings.get("kodi_username", "kodi"), settings.get("kodi_password", ""))
    encoded_credentials = base64.b64encode(credentials.encode('UTF-8'))
    authorization = b'Basic ' + encoded_credentials
    headers = {'Content-Type': 'application/json', 'Authorization': authorization}
    json_data = json.dumps(json.loads(data))
    post_data = json_data.encode('utf-8')
    request = Request(address + "/jsonrpc", post_data, headers)
    try:
        result = urlopen(request).read()
        result = json.loads(result.decode("utf-8"))
        log(result)
        return result
    except:
        return None


def get_refs_from_file(path, xpath):
    font_refs = []
    xml_file = os.path.basename(path)
    root = get_root_from_file(path)
    if root is not None:
        for node in root.xpath(xpath):
            if not node.getchildren():
                item = {"line": node.sourceline,
                        "type": node.tag,
                        "name": node.text,
                        "filename": xml_file,
                        "file": path}
                font_refs.append(item)
    return font_refs
