import os
import json
import argparse
import requests
import platform
from functools import partial
from fucker import Fucker
from logger import logger
from ObjDict import ObjDict
from utils import showImage, cookie_jar_to_list
from utils import getConfigPath, getRealPath, versionCmp

DEFAULT_CONFIG = {
    "username": "",
    "password": "",
    "qrlogin": True,
    "save_cookies": True,
    "proxies": {},
    "logLevel": "INFO",
    "tree_view": True,
    "progressbar_view": True,
    "qr_extra": {
        "show_in_terminal": None,
        "ensure_unicode": False
    },
    "image_path":"",
    "pushplus": {
        "enable": False,
        "token": ""
    },
    "bark":{
        "enable": False,
        "token": ""
    },
    "config_version": "1.5.0",
    "ai": {
        "enabled": False,
        "use_zhidao_ai": True,
        "openai": {
            "api_base": "https://api.openai.com/v1",
            "api_key": "",
            "model_name": "gpt-4o-mini"
        },
        "ppt_processing": {
            "provide_to_ai": False,
            "moonShot": {
                "base_url": "https://api.moonshot.cn/v1",
                "api_key": "",
                "delete_after_convert": True
            }
        },
        "use_stream": True
    }
}
def main(argv=None):
    # get config or create one if not exist
    parser = argparse.ArgumentParser(prog="ZHS Fucker")
    parser.add_argument("-c", "--course", type=str, nargs="+",
                        help="CourseId or recruitAndCourseId, can be found in URL")
    parser.add_argument("-v", "--videos", type=str, nargs="+",
                        help="Video IDs(fileId in URL, or, videoId found in API response")
    parser.add_argument("-u", "--username", type=str,
                        help="if not set anywhere, will be prompted")
    parser.add_argument("-p", "--password", type=str,
                        help="If not set anywhere, will be prompted")
    parser.add_argument("-s", "--speed", type=float)
    parser.add_argument("-t", "--threshold", type=float)
    parser.add_argument("-l", "--limit", type=int, default=0)
    parser.add_argument("-q", "--qrlogin", action="store_true")
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("-f", "--fetch", action="store_true")
    parser.add_argument("--show_in_terminal", action="store_true")
    parser.add_argument("--proxy", type=str)
    parser.add_argument("--tree_view", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--progressbar_view", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--image_path", type=str)
    parser.add_argument("-ai", "--aicourse", type=str, nargs=2,
                        metavar=("COURSE_ID", "CLASS_ID"))
    parser.add_argument("--noexam", action="store_true")
    args = parser.parse_args(argv)

    config_path = getConfigPath()
    legacy_config_path = getRealPath('config.json')
    if not os.path.exists(config_path) and os.path.isfile(legacy_config_path):
        config_path = legacy_config_path

    if os.path.isfile(config_path):
        with open(config_path, 'r+', encoding="UTF-8") as f:
            # 不指定编码格式会导致config中可能存在的中文字符乱码
            try:
                config = ObjDict(json.load(f), default=None)
            except json.JSONDecodeError as e:
                message = (
                    f"Configuration file contains invalid JSON at line {e.lineno}, "
                    f"column {e.colno}; the original file was left unchanged: {config_path}"
                )
                logger.error("Configuration file contains invalid JSON; original file was left unchanged")
                print(message)
                return 1
            if "config_version" not in config:
                config.config_version = "1.0.0"
            if versionCmp(config.config_version, DEFAULT_CONFIG["config_version"]) < 0:
                old_config_version = config.config_version
                new = ObjDict(DEFAULT_CONFIG, default=None)
                if versionCmp(config.config_version, "1.0.1") < 0:
                    config.pop("qr_extra", None)
                if versionCmp(config.config_version, "1.3.0") < 0:
                    pushplus = config.pop("push", {})
                    new.pushplus.update(pushplus)
                config.pop("config_version", None)
                new.update(config)
                # AI was enabled by default in older releases. Disable it during
                # migration; users can explicitly enable it again in config.
                if versionCmp(old_config_version, "1.5.0") < 0:
                    if not isinstance(new.get("ai"), dict):
                        new.ai = ObjDict(DEFAULT_CONFIG["ai"], default=None)
                    new.ai.enabled = False
                new.config_version = DEFAULT_CONFIG["config_version"]
                config = new
                f.seek(0)
                json.dump(config, f, indent=4, ensure_ascii=False)
                f.truncate()
                print("****Config file updated****")
    else:
        config = ObjDict(DEFAULT_CONFIG, default=None)
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

    course = args.course
    username = args.username or config.username
    password = args.password or config.password
    qrlogin = True  # The service currently requires QR login.
    save_cookies = bool(config.save_cookies)
    qr_extra = config.qr_extra or ObjDict(default=None)
    show_in_terminal = args.show_in_terminal or qr_extra.show_in_terminal
    tree_view = config.tree_view if args.tree_view is None else args.tree_view
    progressbar_view = config.progressbar_view if args.progressbar_view is None else args.progressbar_view
    image_path = args.image_path or config.image_path
    if show_in_terminal is None:
        # Defaults to terminal in Windows
        show_in_terminal = platform.system() == "Windows"
    ensure_unicode = qr_extra.ensure_unicode or False
    logger.setLevel("DEBUG" if args.debug else (config.logLevel or "WARNING"))
    proxies = config.proxies or {}
    pushplus_token = config.pushplus.enable and config.pushplus.token or ""
    bark_token = config.bark.enable and config.bark.token or ""

    if logger.getLevel() == "DEBUG":
        print("*****************************\n" +
              "DEBUG MODE ENABLED\n" +
              "Sensitive request data is redacted from logs.\n" +
              "*****************************\n")

    if args.proxy:  # parse proxy
        if "://" not in args.proxy:
            print("*Proxy URL must include a scheme, for example http://127.0.0.1:7897")
            return 1
        match args.proxy.lower().split("://", 1):
            case ["http" | "https", proxy]:
                proxies["http"] = args.proxy
                proxies["https"] = args.proxy
            case ["socks5", proxy]:
                proxies["socks5"] = args.proxy
            case ["all", proxy]:
                proxies["http"] = args.proxy
                proxies["https"] = args.proxy
                proxies["socks5"] = args.proxy
            case [schema]:
                print(f"*Unsupported proxy type: {schema}")
                return 1

    # check update
    with open(getRealPath("meta.json"), "r", encoding="utf-8") as f:
        try:  # some exceptions won't be caught by 'with'
            m = ObjDict(json.load(f))
            url = f"https://raw.githubusercontent.com/{m.author}/fuckZHS/{m.branch}/meta.json"
            update_response = requests.get(url, proxies=proxies, timeout=5)
            update_response.raise_for_status()
            r = ObjDict(update_response.json())
            current = m.version
            latest = r.version
            if versionCmp(current, latest) < 0:
                print("*********************************\n" +
                      f"New version available: {latest}\n" +
                      f"Current version: {current}\n" +
                      "*********************************\n")
        except (OSError, ValueError, KeyError, requests.RequestException):
            print("*Failed to check update\n")

    # create an instance, now we are talking... or fucking
    fucker = Fucker(proxies=proxies, speed=args.speed, end_thre=args.threshold, limit=args.limit,
                    pushplus_token=pushplus_token, bark_token=bark_token, tree_view=tree_view, progressbar_view=progressbar_view, image_path=image_path)

    cookies_path = os.path.join(os.path.dirname(config_path), "cookies.json")
    cookies_loaded = False
    if save_cookies and os.path.exists(cookies_path):
        try:
            with open(cookies_path, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            fucker.cookies = cookies
            ls = fucker.getZhidaoList()
            if ls:
                fucker.getZhidaoContext(ls[-1].secret)
            ls = fucker.getHikeList()
            if ls:
                fucker.getHikeContext(ls[-1].courseId)

            ls = fucker.getZhidaoAiList()
            if ls:
                pass
            print("Successfully recovered from saved cookies\n")
            cookies_loaded = True
        except (OSError, ValueError, requests.RequestException):
            logger.warning("Saved login session could not be restored; QR login will be used.")


    # first you need to login to get cookies
    if not cookies_loaded:
        try:
            if qrlogin:
                callback = partial(
                    showImage, show_in_terminal=show_in_terminal, ensure_unicode=ensure_unicode)
                fucker.login(use_qr=True, qr_callback=callback)
            else:
                fucker.login(username, password)
            print("Login Successful\n")
            if save_cookies:
                with open(cookies_path, 'w', encoding='utf-8') as f:
                    json.dump(cookie_jar_to_list(fucker.cookies), f,
                              indent=2, ensure_ascii=False)
        except Exception:
            logger.error("Login failed; check connectivity and try QR login again.")
            return 1

    # you can add cookies manually by setting cookies property of a Fucker instance
    # notice that cookies of zhihuishu.com expires if you login again in somewhere else
    # fucker.cookies = {}

    if args.aicourse:
        course_id, class_id = args.aicourse
        try:
            def validate_config(config):
                ai_config = config.get("ai", {})
            
                if not isinstance(ai_config, dict):
                    raise ValueError("AI配置不是字典，请检查配置文件")

                if ai_config.get("enabled", False) and not ai_config.get("use_zhidao_ai", False):
                    validate_openai_config(ai_config.get("openai", {}))
            
                validate_ppt_config(ai_config.get("ppt_processing", {}))

            def validate_openai_config(openai_config):
                if not isinstance(openai_config, dict):
                    raise ValueError(f"OpenAI配置不是字典，而是{type(openai_config)}，请检查配置文件")
            
                required_fields = ["api_key", "api_base", "model_name"]
                missing_fields = [field for field in required_fields if not openai_config.get(field)]
                if openai_config.get("api_key", "").strip() in ("sk-", ""):
                    missing_fields.append("有效 api_key")
            
                if missing_fields:
                    raise ValueError(f"OpenAI配置不完整，缺少以下字段：{', '.join(missing_fields)}。请检查配置文件")

            def validate_ppt_config(ppt_config):
                if not isinstance(ppt_config, dict):
                    raise ValueError(f"PPT处理配置不是字典，而是{type(ppt_config)}，请检查配置文件")
            
                if ppt_config.get("provide_to_ai", False):
                    moonShot_conf = ppt_config.get("moonShot", {})
                    required_fields = ["base_url", "api_key"]
                    missing_fields = [field for field in required_fields if not moonShot_conf.get(field)]
                    if moonShot_conf.get("api_key", "").strip() in ("sk-", ""):
                        missing_fields.append("有效 api_key")
                
                    if missing_fields:
                        raise ValueError(f"PPT处理配置不完整，缺少以下字段：{', '.join(missing_fields)}。请检查配置文件")

            # 使用示例
            try:
                validate_config(config)
            except ValueError as e:
                print(f"配置错误: {e}")
                return 1

            if args.noexam:
                no_exam = True
            else:
                no_exam = False

            fucker.fuckAiCourse(course_id, class_id, aiConfig=config.ai, no_exam = no_exam)
        except Exception as e:
            logger.error(f"AI course operation failed: {type(e).__name__}")
            print(f"Error when processing AI course {course_id}: {type(e).__name__}")
            return 1
        finally:
            print("AI exam finished")
        return 0


    exec_list = getRealPath("execution.json")
    # fetch course list
    if args.fetch:
        with open(exec_list, "w", encoding='utf-8') as f:
            zhidao_ids = [{"name": c.courseName, "id": c.secret}
                          for c in fucker.getZhidaoList()]
            hike_ids = [{"name": c.courseName, "id": str(
                c.courseId)} for c in fucker.getHikeList()]
            json.dump(zhidao_ids + hike_ids, f, indent=4, ensure_ascii=False)
        return 0

    # get courses from file if not specified
    if not course and os.path.isfile(exec_list):
        with open(exec_list, "r", encoding='utf-8') as f:
            try:
                course = [str(c["id"]) for c in json.load(f)]
            except Exception as e:
                print(f"*Failed to load course list from file: {e}")
                return 1

    # still not found?
    if not course:
        fucker.fuckWhatever()
        return 0

    # auto detect mode
    for c in course.copy():
        if args.videos:
            for v in args.videos:
                try:
                    fucker.fuckVideo(course_id=c, video_id=v)
                    print(f"fucked {v}")
                    args.videos.remove(v)
                except Exception:
                    pass
        else:
            try:
                fucker.fuckCourse(course_id=c)
                course.remove(c)
            except Exception as e:
                logger.error(f"Course operation failed for {c}: {type(e).__name__}")
                print(f"Error when processing course {c}: {type(e).__name__}")
    if args.videos:
        print(f"*the following videos are not fucked: {args.videos}")

    # use fuckCourse method to fuck the entire course
    # fucker.fuckCourse(course_id="")

    # or if you want to fuck a video, use fuckVideo method
    # fucker.fuckVideo(course_id="", file_id="")

    # check the source code or README to find more info
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
