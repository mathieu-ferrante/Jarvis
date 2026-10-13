"""Catalogue figé de ce que le diagnostic J0 télécharge et mesure.

Versions, révisions et empreintes SHA-256 relevées le 2026-10-13. Les figer garantit que les
mesures sont reproductibles et que rien d'autre que ces fichiers n'est récupéré.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.telechargement import Fichier

# --- llama.cpp ------------------------------------------------------------------------------

LLAMA_CPP_VERSION = "b11583"
_GH_LLAMA = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}"

LLAMA_CPP = {
    # Voie principale sur la RX 6750 XT (RDNA2, gfx1031) : Vulkan.
    "vulkan": Fichier(
        f"{_GH_LLAMA}/llama-{LLAMA_CPP_VERSION}-bin-win-vulkan-x64.zip",
        f"llama.cpp/{LLAMA_CPP_VERSION}-vulkan.zip",
        32112442,
        "fa492c41bb38bd3c607aee3580cc02fc432fe771ed9fd1ccceb74f034d82769f",
    ),
    # ROCm sous Windows : gfx1031 n'est pas officiellement pris en charge. Mesuré pour en avoir
    # le cœur net, sans le supposer (option --avec-rocm).
    "rocm": Fichier(
        f"{_GH_LLAMA}/llama-{LLAMA_CPP_VERSION}-bin-win-rocm-10.0-x64.zip",
        f"llama.cpp/{LLAMA_CPP_VERSION}-rocm.zip",
        257967872,
        "39c69d983fba9d16b154044bc948043bc248c80df1be8cb1a71b46f7ba8668aa",
    ),
    # Repli CPU (mode jeu, ou poste sans GPU).
    "cpu": Fichier(
        f"{_GH_LLAMA}/llama-{LLAMA_CPP_VERSION}-bin-win-cpu-x64.zip",
        f"llama.cpp/{LLAMA_CPP_VERSION}-cpu.zip",
        19509591,
        "2bceb716d9d93b950c008c9d81701650965c33e957de9e1d4da325c35c41abfe",
    ),
}

# whisper.cpp ne publie pas de binaire Windows Vulkan : seule la version CPU est récupérée.
# Une version Vulkan compilée à la main peut être fournie avec --whisper-vulkan.
WHISPER_CPP_CPU = Fichier(
    "https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip",
    "whisper.cpp/b5454-cpu.zip",
    8928640,
    "6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb",
)


def _hf(repo: str, rev: str, chemin: str, taille: int, sha256: str, dest: str | None = None) -> Fichier:
    dossier = repo.split("/")[-1]
    return Fichier(
        f"https://huggingface.co/{repo}/resolve/{rev}/{chemin}",
        dest or f"{dossier}/{chemin.split('/')[-1]}",
        taille,
        sha256,
    )


# --- Modèles de langage ---------------------------------------------------------------------


@dataclass(frozen=True)
class ModeleLLM:
    cle: str
    nom: str
    role: str  # "principal" (raisonnement, outils), "rapide" (routage) ou "test" (poste de dev)
    gguf: Fichier
    mmproj: Fichier | None = None  # projecteur vision (BRN-06)
    # Options propres au modèle pour llama-server (ex. décharger les experts MoE en RAM).
    options_serveur: tuple[str, ...] = ()
    optionnel: bool = False
    notes: str = ""


_QWEN9 = ("unsloth/Qwen3.5-9B-GGUF", "3885219b6810b007914f3a7950a8d1b469d598a5")
_GEMMA12 = ("unsloth/gemma-4-12b-it-GGUF", "fc034cfff751157913579611efad8462ac1be606")
_MINI14 = ("mistralai/Ministral-3-14B-Instruct-2512-GGUF", "74fac473c43357d7fb2671713608183cc72496d0")

MODELES_LLM: list[ModeleLLM] = [
    ModeleLLM(
        "qwen3.5-9b",
        "Qwen3.5 9B (Q4_K_M)",
        "principal",
        _hf(*_QWEN9, "Qwen3.5-9B-Q4_K_M.gguf", 5680522464,
            "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8"),
        _hf(*_QWEN9, "mmproj-F16.gguf", 918166080,
            "f70dc3509053962b0d0d3ee8a7eacebf5d60aa560cad78254ae8698516ae029f",
            "Qwen3.5-9B-GGUF/mmproj-Qwen3.5-9B-F16.gguf"),
        notes="Réputé fort en appel d'outils ; multimodal.",
    ),
    ModeleLLM(
        "gemma-4-12b",
        "Gemma 4 12B (Q4_K_M)",
        "principal",
        _hf(*_GEMMA12, "gemma-4-12b-it-Q4_K_M.gguf", 7121861440,
            "0a270ec9fe6b34f4a0d33992b6135117b484ebc4766ab76b51d4ae8c457e4c42"),
        _hf(*_GEMMA12, "mmproj-F16.gguf", 175115840,
            "91f086971e56d7a7d8d39e271873fccdb49541bd259d6e02c401a4f1cb7a219e",
            "gemma-4-12b-it-GGUF/mmproj-gemma-4-12b-F16.gguf"),
        notes="Jetons d'appel de fonction natifs ; multimodal.",
    ),
    ModeleLLM(
        "ministral-3-14b",
        "Ministral 3 14B Instruct (Q4_K_M)",
        "principal",
        _hf(*_MINI14, "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf", 8239593024,
            "824e0f3373e69b84f2cae46fdcb9bd1ebc6ab3bfc7acc125d818b7b8178cc613"),
        _hf(*_MINI14, "Ministral-3-14B-Instruct-2512-BF16-mmproj.gguf", 879258784,
            "ab7616148b7081030fd38e410c9213ce8346a8b0588291c8ca279058e78cfae7"),
        notes="Mistral (français natif), Apache 2.0 ; multimodal. Le plus gros des trois.",
    ),
    ModeleLLM(
        "qwen3.5-4b",
        "Qwen3.5 4B (Q4_K_M)",
        "rapide",
        _hf("unsloth/Qwen3.5-4B-GGUF", "e87f176479d0855a907a41277aca2f8ee7a09523",
            "Qwen3.5-4B-Q4_K_M.gguf", 2740937888,
            "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4"),
        notes="Candidat au routage des commandes simples, et au mode jeu sur CPU.",
    ),
    ModeleLLM(
        "gemma-4-e4b",
        "Gemma 4 E4B (Q4_K_M)",
        "rapide",
        _hf("unsloth/gemma-4-E4B-it-GGUF", "bfc15c382204943c3a8fff0c750b94ae2364d7a3",
            "gemma-4-E4B-it-Q4_K_M.gguf", 4977171584,
            "85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87"),
        notes="Autre candidat au routage.",
    ),
    ModeleLLM(
        "gemma-4-26b-a4b",
        "Gemma 4 26B-A4B MoE (Q4_K_M, experts en RAM)",
        "principal",
        _hf("unsloth/gemma-4-26B-A4B-it-GGUF", "c099eb48e663fd284577b04978a94ffccb261841",
            "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf", 16947541728,
            "f2c28b3dc4776931ac6f879e11f203dec637ea0f14267a86ec8f6165f63f293f"),
        # 17 Go ne tiennent pas dans 12 Go de VRAM : l'ajustement automatique de llama.cpp
        # (--fit, actif par défaut) laisse une partie des experts en RAM.
        optionnel=True,
        notes="Option --avec-moe : plus capable, mais déborde en RAM ; à mesurer.",
    ),
    ModeleLLM(
        "qwen3.5-0.8b",
        "Qwen3.5 0.8B (Q4_K_M)",
        "test",
        _hf("unsloth/Qwen3.5-0.8B-GGUF", "6ab461498e2023f6e3c1baea90a8f0fe38ab64d0",
            "Qwen3.5-0.8B-Q4_K_M.gguf", 532517120,
            "bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517"),
        notes="Uniquement pour valider le script sur le poste de développement (--rapide).",
    ),
]

# --- Transcription --------------------------------------------------------------------------

_TOKENIZER_SYSTRAN = ("tokenizer.json", 2203239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab")
_VOCAB_SYSTRAN = ("vocabulary.txt", 459861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913")


@dataclass(frozen=True)
class ModeleSTT:
    cle: str
    moteur: str  # "faster-whisper" ou "whisper.cpp"
    fichiers: tuple[Fichier, ...]
    test: bool = False  # petit modèle réservé au poste de développement

    @property
    def dossier(self) -> str:
        return self.fichiers[0].destination.split("/")[0]


def _fw_systran(taille: str, rev: str, config: tuple[int, str], modele: tuple[int, str]) -> ModeleSTT:
    repo = f"Systran/faster-whisper-{taille}"
    return ModeleSTT(
        f"fw-{taille}",
        "faster-whisper",
        (
            _hf(repo, rev, "config.json", *config),
            _hf(repo, rev, "model.bin", *modele),
            _hf(repo, rev, *_TOKENIZER_SYSTRAN),
            _hf(repo, rev, *_VOCAB_SYSTRAN),
        ),
        test=taille == "base",
    )


_TURBO = ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf")
_GGML = ("ggerganov/whisper.cpp", "5359861c739e955e79d9a303bcbc70fb988958b1")
_PARAKEET = ("ggml-org/parakeet-GGUF", "35156454d1a39de06863303dd209fd2bed6ee079")

MODELES_STT: list[ModeleSTT] = [
    _fw_systran("base", "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
                (2309, "56a6d8110d311f19c8f0471e562832c7527f146b567275bfca59fcf7c184da9a"),
                (145217532, "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9")),
    _fw_systran("small", "536b0662742c02347bc0e980a01041f333bce120",
                (2370, "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828"),
                (483546902, "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671")),
    _fw_systran("medium", "08e178d48790749d25932bbc082711ddcfdfbc4f",
                (2257, "3622a2ddc41ec0e0fd4e68c13c6830f03b90c38d89aaad184de02c8c642cf807"),
                (1527906378, "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae")),
    ModeleSTT(
        "fw-large-v3-turbo",
        "faster-whisper",
        (
            _hf(*_TURBO, "config.json", 2263, "b0253ea6c0d3bea6b1e19e91a02acfd3b53f4467362efcb5a3e6b16c9b3a9b7e"),
            _hf(*_TURBO, "model.bin", 1617884929, "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da"),
            _hf(*_TURBO, "preprocessor_config.json", 340,
                "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711"),
            _hf(*_TURBO, "tokenizer.json", 2710337, "297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd"),
            _hf(*_TURBO, "vocabulary.json", 1068114,
                "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1"),
        ),
    ),
    ModeleSTT("wcpp-base", "whisper.cpp", (
        _hf(*_GGML, "ggml-base.bin", 147951465,
            "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe", "whisper-ggml/ggml-base.bin"),
    ), test=True),
    ModeleSTT("wcpp-small", "whisper.cpp", (
        _hf(*_GGML, "ggml-small.bin", 487601967,
            "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b", "whisper-ggml/ggml-small.bin"),
    )),
    ModeleSTT("wcpp-large-v3-turbo-q8", "whisper.cpp", (
        _hf(*_GGML, "ggml-large-v3-turbo-q8_0.bin", 874188075,
            "317eb69c11673c9de1e1f0d459b253999804ec71ac4c23c17ecf5fbe24e259a1",
            "whisper-ggml/ggml-large-v3-turbo-q8_0.bin"),
    )),
    # Parakeet TDT 0.6B v3 (NVIDIA, 25 langues européennes dont le français), exécuté par le
    # parakeet-cli de whisper.cpp. Réputé bien plus rapide que Whisper sur CPU.
    ModeleSTT("parakeet-v3-q8", "parakeet", (
        _hf(*_PARAKEET, "ggml-parakeet-tdt-0.6b-v3-q8_0.bin", 668757119,
            "4d64e9e96c2792186d072fde0034df0ad670cf680a2f53069052ead827fd600e"),
    )),
    ModeleSTT("parakeet-v3-q4", "parakeet", (
        _hf(*_PARAKEET, "ggml-parakeet-tdt-0.6b-v3-q4_0.bin", 355615679,
            "aa7fe2f5fb47d863ca23e8b1d490632d63a2599f515268b6d6bd656158dad45e"),
    ), test=True),
]

# --- Voix de synthèse -----------------------------------------------------------------------

_PIPER = ("rhasspy/piper-voices", "c10ece1aade47bb51c153c893d14e5bf8e5b7117")


@dataclass(frozen=True)
class VoixTTS:
    cle: str
    moteur: str  # "piper" ou "kokoro"
    fichiers: tuple[Fichier, ...]
    voix: str = ""  # nom de la voix (Kokoro)
    test: bool = False


def _piper(nom: str, onnx: tuple[int, str], json_: tuple[int, str], test: bool = False) -> VoixTTS:
    base = f"fr/fr_FR/{nom}/medium/fr_FR-{nom}-medium"
    return VoixTTS(
        f"piper-{nom}",
        "piper",
        (
            _hf(*_PIPER, base + ".onnx", *onnx, dest=f"piper/fr_FR-{nom}-medium.onnx"),
            _hf(*_PIPER, base + ".onnx.json", *json_, dest=f"piper/fr_FR-{nom}-medium.onnx.json"),
        ),
        test=test,
    )


_GH_KOKORO = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
_KOKORO_VOIX = Fichier(f"{_GH_KOKORO}/voices-v1.0.bin", "kokoro/voices-v1.0.bin", 28214398,
                       "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d")

VOIX_TTS: list[VoixTTS] = [
    _piper("siwis", (63201294, "641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99"),
           (4875, "39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959"), test=True),
    _piper("tom", (63511038, "bf65074ccdeeeeaa832e75edb1c0a513c01c9a972bdf085ff8a6e71ea234fd41"),
           (4959, "2f7f885ad5a0aad802e3cc24e4f57239febdcb142b4876de5d238094674361cc")),
    _piper("upmc", (76733615, "9abb3800c199148897a9ed64e100d224f3de83579f100044174ad19418f1786f"),
           (4996, "e8636ec15dfd5d72db37a02cb5320a20f2b8d339f2a0e4337da64c58a33a5868")),
    VoixTTS(
        "kokoro-ff_siwis",
        "kokoro",
        (
            Fichier(f"{_GH_KOKORO}/kokoro-v1.0.int8.onnx", "kokoro/kokoro-v1.0.int8.onnx", 92361271,
                    "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb"),
            _KOKORO_VOIX,
        ),
        voix="ff_siwis",
        test=True,
    ),
    VoixTTS(
        "kokoro-ff_siwis-fp32",
        "kokoro",
        (
            Fichier(f"{_GH_KOKORO}/kokoro-v1.0.onnx", "kokoro/kokoro-v1.0.onnx", 325532387,
                    "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"),
            _KOKORO_VOIX,
        ),
        voix="ff_siwis",
    ),
]

# --- Mot de réveil --------------------------------------------------------------------------

_GH_OWW = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
OPENWAKEWORD = {
    "melspectrogram": Fichier(f"{_GH_OWW}/melspectrogram.onnx", "openwakeword/melspectrogram.onnx", 1087958,
                              "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f"),
    "embedding": Fichier(f"{_GH_OWW}/embedding_model.onnx", "openwakeword/embedding_model.onnx", 1326578,
                         "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f"),
    "hey_jarvis": Fichier(f"{_GH_OWW}/hey_jarvis_v0.1.onnx", "openwakeword/hey_jarvis_v0.1.onnx", 1271370,
                          "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb"),
    "silero_vad": Fichier(f"{_GH_OWW}/silero_vad.onnx", "openwakeword/silero_vad.onnx", 1807522,
                          "a35ebf52fd3ce5f1469b2a36158dba761bc47b973ea3382b3186ca15b1f5af28"),
}


@dataclass
class Selection:
    """Ce qu'une exécution du diagnostic va mesurer, selon les options."""

    llm: list[ModeleLLM] = field(default_factory=list)
    stt: list[ModeleSTT] = field(default_factory=list)
    tts: list[VoixTTS] = field(default_factory=list)
    backends: list[str] = field(default_factory=list)

    def fichiers(self) -> list[Fichier]:
        tous: list[Fichier] = [LLAMA_CPP[b] for b in self.backends]
        for m in self.llm:
            tous.append(m.gguf)
            if m.mmproj:
                tous.append(m.mmproj)
        if any(m.moteur in ("whisper.cpp", "parakeet") for m in self.stt):
            tous.append(WHISPER_CPP_CPU)
        for m in self.stt:
            tous.extend(m.fichiers)
        for v in self.tts:
            tous.extend(v.fichiers)
        tous.extend(OPENWAKEWORD.values())
        uniques: dict[str, Fichier] = {}
        for f in tous:
            uniques.setdefault(f.destination, f)
        return list(uniques.values())

    def volume_total(self) -> int:
        return sum(f.taille for f in self.fichiers())


def selection(rapide: bool, avec_moe: bool = False, avec_rocm: bool = False) -> Selection:
    """`rapide` : petits modèles seulement, pour valider le script sur le poste de dev."""
    if rapide:
        return Selection(
            llm=[m for m in MODELES_LLM if m.role == "test"],
            stt=[m for m in MODELES_STT if m.test],
            tts=[v for v in VOIX_TTS if v.test],
            backends=["vulkan", "cpu"],
        )
    return Selection(
        llm=[m for m in MODELES_LLM if m.role in ("principal", "rapide") and (avec_moe or not m.optionnel)],
        stt=[m for m in MODELES_STT if not m.test],
        tts=list(VOIX_TTS),
        backends=["vulkan", "cpu"] + (["rocm"] if avec_rocm else []),
    )
