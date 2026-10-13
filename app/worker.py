import os
from redis import Redis
from rq import Queue, Worker


def main():
    connection = Redis.from_url(os.environ['REDIS_URL'])
    Worker([Queue('pdf', connection=connection)], connection=connection).work()


if __name__ == '__main__':
    main()
