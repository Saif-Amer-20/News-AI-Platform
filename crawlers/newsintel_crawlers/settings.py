import os

BOT_NAME = "newsintel_crawlers"

SPIDER_MODULES = ["newsintel_crawlers.spiders"]
NEWSPIDER_MODULE = "newsintel_crawlers.spiders"

ROBOTSTXT_OBEY = True
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = os.getenv("CRAWLERS_LOG_LEVEL", "INFO")

