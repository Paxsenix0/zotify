import time
import ffmpy
import subprocess
from pathlib import PurePath, Path
from librespot.metadata import EpisodeId

from zotify.config import Zotify
from zotify.const import (
    EPISODE_URL, SHOW_URL, PARTNER_URL, PERSISTED_QUERY, ERROR, ID, ITEMS, NAME,
    SHOW, DURATION_MS, EXT_MAP, IMAGES, URL, WIDTH, RELEASE_DATE, DESCRIPTION,
    HTML_DESCRIPTION, YEAR, IMAGE_URL
)
from zotify.termoutput import PrintChannel, Printer, Loader
from zotify.utils import (
    create_download_directory, fix_filename, fmt_duration, wait_between_downloads,
    set_podcast_tags, set_music_thumbnail
)


def parse_episode_metadata(episode_resp: dict) -> dict:
    """ Parses the API response for an episode into a structured dictionary. """
    episode_metadata = {}

    episode_metadata[ID] = episode_resp[ID]
    episode_metadata[NAME] = episode_resp[NAME]
    episode_metadata[SHOW] = episode_resp[SHOW][NAME]
    episode_metadata[DURATION_MS] = episode_resp[DURATION_MS]
    episode_metadata[RELEASE_DATE] = episode_resp[RELEASE_DATE]
    episode_metadata[YEAR] = episode_metadata[RELEASE_DATE].split('-')[0]
    
    # Use description, fallback to html_description if it exists
    episode_metadata[DESCRIPTION] = episode_resp.get(DESCRIPTION, episode_resp.get(HTML_DESCRIPTION, ''))

    largest_image = max(episode_resp[IMAGES], key=lambda img: img[WIDTH], default=None)
    episode_metadata[IMAGE_URL] = largest_image[URL] if largest_image else ''

    episode_metadata['album'] = episode_metadata[SHOW]
    episode_metadata['artists'] = [episode_metadata[SHOW]]

    return episode_metadata


def get_episode_metadata(episode_id: str) -> dict | None:
    """ Retrieves and parses metadata for a podcast episode. """
    with Loader(PrintChannel.PROGRESS_INFO, "Fetching episode information..."):
        (raw, resp) = Zotify.invoke_url(f'{EPISODE_URL}/{episode_id}')

    if not resp or ERROR in resp:
        Printer.hashtaged(PrintChannel.ERROR, 'INVALID EPISODE ID OR FAILED TO FETCH METADATA')
        return None
    
    try:
        return parse_episode_metadata(resp)
    except Exception as e:
        Printer.hashtaged(PrintChannel.ERROR, f'Failed to parse EPISODE_URL response: {str(e)}')
        return None


def get_show_episode_ids(show_id: str) -> list:
    with Loader(PrintChannel.PROGRESS_INFO, "Fetching episodes..."):
        episodes = Zotify.invoke_url_nextable(f'{SHOW_URL}/{show_id}/episodes', ITEMS)
    return [episode[ID] for episode in episodes]


def download_podcast_directly(url, filename):
    import functools
    import shutil
    import requests
    from tqdm.auto import tqdm

    r = requests.get(url, stream=True, allow_redirects=True)
    if r.status_code != 200:
        r.raise_for_status()
        raise RuntimeError(
            f"Request to {url} returned status code {r.status_code}")
    file_size = int(r.headers.get('Content-Length', 0))

    path = Path(filename).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    desc = "(Unknown total file size)" if file_size == 0 else ""
    r.raw.read = functools.partial(
        r.raw.read, decode_content=True)  # Decompress if needed
    with tqdm.wrapattr(r.raw, "read", total=file_size, desc=desc) as r_raw:
        with path.open("wb") as f:
            shutil.copyfileobj(r_raw, f)

    return path


def download_show(show_id, pbar_stack: list | None = None):
    episode_ids = get_show_episode_ids(show_id)

    pos, pbar_stack = Printer.pbar_position_handler(3, pbar_stack)
    pbar = Printer.pbar(episode_ids, unit='episode', pos=pos,
                        disable=not Zotify.CONFIG.get_show_playlist_pbar())
    pbar_stack.append(pbar)

    for episode in pbar:
        resp = Zotify.invoke_url(f'{EPISODE_URL}/{episode_id}', raw=True)
        pbar.set_description(resp.get(NAME, "Loading..."))
        download_episode(episode, pbar_stack)
        Printer.refresh_all_pbars(pbar_stack)


def download_episode(episode_id, pbar_stack: list | None = None) -> None:
    episode_metadata = get_episode_metadata(episode_id)

    if not episode_metadata:
        Printer.hashtaged(PrintChannel.ERROR, 'SKIPPING EPISODE - FAILED TO QUERY METADATA\n' +\
                                             f'Episode_ID: {str(episode_id)}')
        wait_between_downloads()
        return

    podcast_name = fix_filename(episode_metadata[SHOW])
    episode_name = fix_filename(episode_metadata[NAME])
    duration_ms = episode_metadata[DURATION_MS]

    if Zotify.CONFIG.get_regex_episode():
        regex_match = Zotify.CONFIG.get_regex_episode().search(episode_name)
        if regex_match:
            Printer.hashtaged(PrintChannel.SKIPPING, 'EPISODE MATCHES REGEX FILTER\n' +\
                                                    f'Episode_Name: {episode_name} - Episode_ID: {episode_id}\n'+\
                                                   (f'Regex Groups: {regex_match.groupdict()}' if regex_match.groups() else ""))
            wait_between_downloads(); return

    with Loader(PrintChannel.PROGRESS_INFO, "Preparing download..."):
        filename = f"{podcast_name} - {episode_name}"
        episode_path = PurePath(Zotify.CONFIG.get_root_podcast_path()) / podcast_name / f"{filename}"
        create_download_directory(episode_path.parent)

        (raw, resp) = Zotify.invoke_url(PARTNER_URL + episode_id + '"}&extensions=' + PERSISTED_QUERY)
        direct_download_url = resp["data"]["episode"]["audio"]["items"][-1]["url"]

        if "anon-podcast.scdn.co" in direct_download_url or "audio_preview_url" not in resp:
            episode_id_obj = EpisodeId.from_base62(episode_id)
            stream = Zotify.get_content_stream(episode_id_obj, Zotify.DOWNLOAD_QUALITY)

            if stream is None:
                Printer.hashtaged(PrintChannel.ERROR, 'SKIPPING EPISODE - FAILED TO GET CONTENT STREAM\n' +\
                                                     f'Episode_ID: {str(episode_id)}')
                wait_between_downloads(); return

            episode_exists_on_filesystem = False
            total_size: int = stream.input_stream.size
            for extension_list_item in set(EXT_MAP.values()):
                test_episode_path = Path(episode_path).with_suffix("." + extension_list_item)
                if test_episode_path.is_file():
                    Printer.debug(f"FILE EXISTS: {test_episode_path}")
                    Printer.debug(f"FILE SIZE: {test_episode_path.stat().st_size } STREAM SIZE: {total_size}")                    
                    if test_episode_path.stat().st_size >= (total_size - 1024) and Zotify.CONFIG.get_skip_existing(): # Final file sizes can be slightly smaller than reported stream size.  Check that it's within a kilobyte
                        Printer.hashtaged(PrintChannel.SKIPPING, f'"{podcast_name} - {episode_name}" (EPISODE ALREADY EXISTS)')
                        episode_exists_on_filesystem = True
                        break
            if episode_exists_on_filesystem == True:
                wait_between_downloads(); return

            episode_path = Path(episode_path).with_suffix(".tmp")            
            time_start = time.time()
            downloaded = 0
            pos, pbar_stack = Printer.pbar_position_handler(1, pbar_stack)
            with open(episode_path, 'wb') as file, Printer.pbar(
                desc=filename,
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                disable=not Zotify.CONFIG.get_show_download_pbar(),
                pos=pos
            ) as pbar:
                b = 0
                while b < 5:
                    data = stream.input_stream.stream().read(Zotify.CONFIG.get_chunk_size())
                    pbar.update(file.write(data))
                    downloaded += len(data)
                    b += 1 if data == b'' else 0
                    if Zotify.CONFIG.get_download_real_time():
                        delta_real = time.time() - time_start
                        delta_want = (downloaded / total_size) * (int(duration_ms)/1000)
                        if delta_want > delta_real:
                            time.sleep(delta_want - delta_real)

            time_dl_end = time.time()
            time_elapsed_dl = fmt_duration(time_dl_end - time_start)
        else:
            time_start = time.time()
            download_podcast_directly(direct_download_url, episode_path)
            time_dl_end = time.time()
            time_elapsed_dl = fmt_duration(time_dl_end - time_start)

    Printer.hashtaged(PrintChannel.DOWNLOADS, f'DOWNLOADED: "{filename}"\n' +\
                                              f'DOWNLOAD TOOK {time_elapsed_dl}')

    episode_path_codec = None
    try:
        with Loader(PrintChannel.PROGRESS_INFO, "Identifying episode audio codec..."):
            ff_m = ffmpy.FFprobe(
                global_options=['-hide_banner', f'-loglevel {Zotify.CONFIG.get_ffmpeg_log_level()}'],
                inputs={episode_path: ["-show_entries", "stream=codec_name"]},
            )
            stdout, _ = ff_m.run(stdout=subprocess.PIPE)
            codec = stdout.decode().strip().split("=")[1].split("\r")[0].split("\n")[0]

            if codec in EXT_MAP:
                suffix = EXT_MAP[codec]
            else:
                suffix = codec

            episode_path_codec = episode_path.with_suffix(f".{suffix}")
            if Path(episode_path_codec).exists():
                Path(episode_path_codec).unlink()
            Path(episode_path).rename(episode_path_codec)

        Printer.debug(f"Detected Codec: {codec}\n" +\
                      f"File Renamed: {episode_path_codec.name}")

    except ffmpy.FFExecutableNotFoundError:
        episode_path_codec = episode_path.with_suffix(".mp3")
        Path(episode_path).rename(episode_path_codec)
        Printer.hashtaged(PrintChannel.WARNING, 'FFMPEG NOT FOUND\n' +\
                                                'SKIPPING CODEC ANALYSIS - OUTPUT ASSUMED MP3')

    if episode_path_codec and episode_path_codec.exists():
        try:
            with Loader(PrintChannel.PROGRESS_INFO, "Applying metadata..."):
                # For podcasts, genre isn't provided, so we'll just set it to "Podcast"
                genres = ["Podcast"]
                set_podcast_tags(episode_path_codec, episode_metadata, genres=genres)
                if episode_metadata[IMAGE_URL]:
                    set_music_thumbnail(episode_path_codec, episode_metadata[IMAGE_URL], mode="podcast")
        except Exception as e:
            Printer.hashtaged(PrintChannel.ERROR, 'FAILED TO WRITE METADATA\n' + \
                                                  'Ensure FFMPEG is installed and added to your PATH')
            Printer.traceback(e)

    wait_between_downloads()