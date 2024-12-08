from enum import StrEnum
import os
from dotenv import load_dotenv

load_dotenv()

voice_lookups = {
    "Sonia_GB": "en-GB-SoniaNeural",
    "Libby_GB": "en-GB-LibbyNeural",
    "Asilia_KE": "en-KE-AsiliaNeural",
    "Emma_US": "en-US-EmmaNeural",
    "Ava_US": "en-US-AvaNeural",
    "Natasha_AU": "en-AU-NatashaNeural",
    "Mitchell_NZ": "en-NZ-MitchellNeural",
    "Chilemba_KE": "en-KE-ChilembaNeural",
    "William_AU": "en-AU-WilliamNeural",
    "Clara_CA": "en-CA-ClaraNeural",
    "Liam_CA": "en-CA-LiamNeural",
    "Maisie_GB": "en-GB-MaisieNeural",
    "Ryan_GB": "en-GB-RyanNeural",
    "Thomas_GB": "en-GB-ThomasNeural",
    "Sam_HK": "en-HK-SamNeural",
    "Yan_HK": "en-HK-YanNeural",
    "Connor_IE": "en-IE-ConnorNeural",
    "Emily_IE": "en-IE-EmilyNeural",
    "Neerja_IN": "en-IN-NeerjaNeural",
    "Prabhat_IN": "en-IN-PrabhatNeural",
    "Chilemba_KE": "en-KE-ChilembaNeural",
    "Abeo_NG": "en-NG-AbeoNeural",
    "Ezinne_NG": "en-NG-EzinneNeural",
    "Molly_NZ": "en-NZ-MollyNeural",
    "James_PH": "en-PH-JamesNeural",
    "Rosa_PH": "en-PH-RosaNeural",
    "Luna_SG": "en-SG-LunaNeural",
    "Wayne_SG": "en-SG-WayneNeural",
    "Elimu_TZ": "en-TZ-ElimuNeural",
    "Imani_TZ": "en-TZ-ImaniNeural",
    "Ana_US": "en-US-AnaNeural",
    "Andrew_US": "en-US-AndrewNeural",
    "Aria_US": "en-US-AriaNeural",
    "Brian_US": "en-US-BrianNeural",
    "Christopher_US": "en-US-ChristopherNeural",
    "Eric_US": "en-US-EricNeural",
    "Guy_US": "en-US-GuyNeural",
    "Jenny_US": "en-US-JennyNeural",
    "Michelle_US": "en-US-MichelleNeural",
    "Roger_US": "en-US-RogerNeural",
    "Steffan_US": "en-US-SteffanNeural",
    "Leah_ZA": "en-ZA-LeahNeural",
    "Luke_ZA": "en-ZA-LukeNeural",
}


class Process(StrEnum):
    GUTENBURG_TEXT = "gutenberg_to_text"
    GUTENBURG_MP3 = "gutenberg_to_mp3"
    PDF_TO_TEXT = "pdf_to_text"
    PDF_TO_MP3 = "pdf_to_mp3"
    TEXT_TO_MP3 = "text_to_mp3"
    SAMPLE_VOICE = "sample_voice"

    @classmethod
    def options(cls):
        return list([c.value for c in cls])


VOICES = list(voice_lookups.keys())
DEFAULT_VOICE = os.environ.get("DEFAULT_VOICE", "Sonia_GB")
DEFAULT_PROCESS = os.environ.get("DEFAULT_PROCESS", Process.SAMPLE_VOICE)
DEFAULT_SPEED = os.environ.get("DEFAULT_SPEED", "+0%")
OUTPUT_DIRECTORY = os.environ.get("OUTPUT_DIRECTORY", "")
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(filename)s (%(levelname)s):\t%(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
