"""Local storage for development; private S3-compatible objects for deployment."""
import os
from pathlib import Path
from typing import Protocol


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def read(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalObjectStorage:
    def __init__(self):
        self.root = Path(os.getenv('ASSET_STORAGE_DIR', str(Path(os.getenv('PDF_STORAGE_DIR', 'storage/pdfs')).parent / 'assets'))).resolve()

    def path(self, key):
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Invalid storage key')
        return path

    def put(self, key, data, content_type):
        from tempfile import NamedTemporaryFile
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with NamedTemporaryFile(dir=path.parent, delete=False, suffix='.tmp') as stream:
                temp = Path(stream.name)
                stream.write(data)
            temp.replace(path)  # Writer is closed before promotion, including on Windows.
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    def read(self, key):
        return self.path(key).read_bytes()

    def exists(self, key):
        return self.path(key).is_file()


class S3ObjectStorage:
    def __init__(self):
        import boto3
        self.bucket = os.environ['OBJECT_STORAGE_BUCKET']
        self.client = boto3.client('s3', endpoint_url=os.getenv('OBJECT_STORAGE_ENDPOINT') or None,
                                   region_name=os.getenv('OBJECT_STORAGE_REGION', 'us-east-1'),
                                   aws_access_key_id=os.getenv('OBJECT_STORAGE_ACCESS_KEY_ID') or None,
                                   aws_secret_access_key=os.getenv('OBJECT_STORAGE_SECRET_ACCESS_KEY') or None)

    def put(self, key, data, content_type):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def read(self, key):
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        try:
            return response['Body'].read()
        finally:
            response['Body'].close()

    def exists(self, key):
        from botocore.exceptions import ClientError
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as error:
            if error.response['Error']['Code'] in {'404', 'NoSuchKey', 'NotFound'}:
                return False
            raise


def object_storage() -> ObjectStorage:
    backend = os.getenv('OBJECT_STORAGE_BACKEND', 'local')
    if backend == 's3':
        return S3ObjectStorage()
    if backend != 'local':
        raise ValueError('Unsupported object storage backend')
    return LocalObjectStorage()
