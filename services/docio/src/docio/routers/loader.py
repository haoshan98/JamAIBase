import sys
from os.path import splitext
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, UploadFile
from fastapi.exceptions import RequestValidationError
from langchain_community import document_loaders as loaders
from loguru import logger
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from s3fs import S3FileSystem

from docio.langchain.pdfplumber import PDFPlumberLoader
from jamaibase.protocol import Document

# from unstructured_client import UnstructuredClient
# from unstructured_client.models import shared
# from unstructured_client.models.errors import SDKError


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    s3_key: str = "minioadmin"  # MinIO key
    s3_secret: SecretStr = "fasts3xystoragelabel"
    s3_url: str = "http://10.103.68.103:9000"
    unstructuredio_url: str = "http://unstructuredio:6989/general/v0/general"
    unstructuredio_api_key: SecretStr = "ellm"

    @property
    def s3_secret_plain(self):
        return self.s3_secret.get_secret_value()

    @property
    def unstructuredio_api_key_plain(self):
        return self.unstructuredio_api_key.get_secret_value()


config = Config()
router = APIRouter()


@router.on_event("startup")
async def startup():
    # Router lifespan is broken as of fastapi==0.109.0 and starlette==0.35.1
    # https://github.com/tiangolo/fastapi/discussions/9664
    logger.info(f"DocLoader router config: {config}")

    # --- S3 Client --- #
    global s3_client
    s3_client = S3FileSystem(
        key=config.s3_key,
        secret=config.s3_secret_plain,
        endpoint_url=config.s3_url,
        # asynchronous=True,
    )

    # s3_session = await s3_client.set_session()


# build a table mapping all non-printable characters to None
NOPRINT_TRANS_TABLE = {
    i: None for i in range(0, sys.maxunicode + 1) if not chr(i).isprintable() and chr(i) != "\n"
}


def make_printable(s: str) -> str:
    """
    Replace non-printable characters in a string using
    `translate()` that removes characters that map to None.

    # https://stackoverflow.com/a/54451873
    """
    return s.translate(NOPRINT_TRANS_TABLE)


def load_file(file_path: str) -> list[Document]:
    ext = splitext(file_path)[1].lower()
    if ext in (".txt", ".md"):
        loader = loaders.TextLoader(file_path)
    elif ext == ".pdf":
        loader = PDFPlumberLoader(file_path)
    elif ext == ".csv":
        loader = loaders.CSVLoader(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    documents = loader.load()
    logger.info(f"docio {str(documents)}")
    documents = [
        Document(
            # TODO: Probably can use regex for this
            # Replace vertical tabs, form feed, Unicode replacement character
            # page_content=d.page_content.replace("\x0c", " ")
            # .replace("\x0b", " ")
            # .replace("\uFFFD", ""),
            # For now we use a more aggressive strategy
            page_content=make_printable(d.page_content),
            metadata={"page": d.metadata.get("page", 0), **d.metadata},
        )
        for d in documents
    ]
    return documents


@router.post("/v1/load_file")
async def load_file_api(
    file: UploadFile = File(
        description="File to be uploaded in the form of `multipart/form-data`."
    ),
) -> list[Document]:
    logger.info(
        "Upload type: {content_type} {filename}",
        content_type=file.content_type,
        filename=file.filename,
    )
    try:
        ext = splitext(file.filename)[1]

        with NamedTemporaryFile(suffix=ext) as tmp:
            tmp.write(await file.read())
            tmp.flush()
            logger.trace("Loading from temporary file: {name}", name=tmp.name)

            documents = load_file(tmp.name)
        for d in documents:
            d.metadata["source"] = file.filename
            d.metadata["document_id"] = file.filename
        return documents
    except RequestValidationError:
        raise
    except Exception:
        logger.exception("Failed to load file.")
        raise
