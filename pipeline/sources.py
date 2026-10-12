"""Raw data sources: where each file comes from and where it is cached under data/raw/."""

from dataclasses import dataclass

# Pinned to the commit that published the data, so a re-run gets byte-identical files.
_TIDYTUESDAY = (
    "https://raw.githubusercontent.com/rfordatascience/tidytuesday/"
    "993a0a85770cb68c443807c6d69a956c89f4b707/data/2022/2022-02-01"
)
_STANFORD = "http://vision.stanford.edu/aditya86/ImageNetDogs"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    filename: str  # relative to the raw data directory
    api_key_env: str | None = None  # sent as the x-api-key header, read from this env var
    extract: bool = False  # unpack the tar archive into a folder next to it


AKC_BREED_TRAITS = Source(
    name="akc_breed_traits",
    url=f"{_TIDYTUESDAY}/breed_traits.csv",
    filename="akc/breed_traits.csv",
)
AKC_TRAIT_DESCRIPTIONS = Source(
    name="akc_trait_descriptions",
    url=f"{_TIDYTUESDAY}/trait_description.csv",
    filename="akc/trait_description.csv",
)
DOG_API_BREEDS = Source(
    name="dog_api_breeds",
    url="https://api.thedogapi.com/v1/breeds",
    filename="dog_api/breeds.json",
    api_key_env="DOG_API_KEY",  # pragma: allowlist secret (env var name, not a key)
)
# Official train/test split and the 120 class folder names (MATLAB .mat files).
STANFORD_LISTS = Source(
    name="stanford_lists",
    url=f"{_STANFORD}/lists.tar",
    filename="stanford/lists.tar",
    extract=True,
)

BREED_SOURCES: tuple[Source, ...] = (
    AKC_BREED_TRAITS,
    AKC_TRAIT_DESCRIPTIONS,
    DOG_API_BREEDS,
    STANFORD_LISTS,
)

_OXFORD = "https://www.robots.ox.ac.uk/~vgg/data/pets/data"

# Large image archives (~1.6 GB together). Never committed: the licences forbid it.
STANFORD_IMAGES = Source(
    name="stanford_images",
    url=f"{_STANFORD}/images.tar",
    filename="stanford/images.tar",
    extract=True,
)
# Oxford-IIIT Pet: external test set (dogs) and not-a-dog checks (cats) only.
OXFORD_IMAGES = Source(
    name="oxford_images",
    url=f"{_OXFORD}/images.tar.gz",
    filename="oxford/images.tar.gz",
    extract=True,
)
OXFORD_ANNOTATIONS = Source(
    name="oxford_annotations",
    url=f"{_OXFORD}/annotations.tar.gz",
    filename="oxford/annotations.tar.gz",
    extract=True,
)

IMAGE_SOURCES: tuple[Source, ...] = (STANFORD_IMAGES, OXFORD_IMAGES, OXFORD_ANNOTATIONS)
