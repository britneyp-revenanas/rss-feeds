import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
from feedgen.feed import FeedGenerator
import logging
from pathlib import Path
import re
import hashlib

from utils import get_feeds_dir, sort_posts_for_feed

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def fetch_changelog_content(url="https://www.clay.com/changelog"):
    """Fetch changelog content from Clay's website."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error(f"Error fetching changelog content: {str(e)}")
        raise


def parse_date(date_text):
    """Parse date from various formats used on Clay changelog."""
    date_formats = [
        "%b %d, %Y",  # Feb 13, 2026
        "%B %d, %Y",  # February 13, 2026
        "%b %d %Y",
        "%B %d %Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
    ]

    date_text = date_text.strip()
    for date_format in date_formats:
        try:
            date = datetime.strptime(date_text, date_format)
            return date.replace(tzinfo=pytz.UTC)
        except ValueError:
            continue

    logger.warning(f"Could not parse date: {date_text}")
    return None


def parse_changelog_html(html_content):
    """Parse the changelog HTML content and extract entries."""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        changelog_entries = []

        # Find all rows that contain changelog entries
        rows = soup.find_all(class_="row")
        timeline_rows = [row for row in rows if row.find(class_="cc-timeline-date")]

        for row in timeline_rows:
            date_div = row.find(class_="cc-timeline-date")
            body_div = row.find(class_="cc-timeline-body")

            if not date_div or not body_div:
                continue

            # Extract date
            date_text = date_div.get_text(strip=True)
            date = parse_date(date_text)

            if not date:
                logger.warning(f"Skipping entry with unparseable date: {date_text}")
                continue

            # Extract title from h2 or h3
            title_elem = body_div.find(["h1", "h2", "h3", "h4"])
            title = title_elem.get_text(strip=True) if title_elem else f"Clay Update - {date_text}"

            # Extract description from rtf_changelog
            rtf = body_div.find(class_="rtf_changelog")
            if rtf:
                # Build HTML description from list items
                description_parts = []
                for child in rtf.children:
                    if child.name == "li":
                        # Get bold text as feature name
                        strong = child.find("strong")
                        if strong:
                            feature_name = strong.get_text(strip=True)
                            # Get remaining text as description
                            remaining = child.get_text(strip=True)
                            if remaining.startswith(feature_name):
                                remaining = remaining[len(feature_name):].strip()
                                if remaining.startswith("-"):
                                    remaining = remaining[1:].strip()
                            description_parts.append(f"<p><strong>{feature_name}</strong>: {remaining}</p>")
                        else:
                            description_parts.append(f"<p>{child.get_text(strip=True)}</p>")
                    elif child.name == "ul":
                        items = [f"<li>{li.get_text(strip=True)}</li>" for li in child.find_all("li")]
                        description_parts.append(f"<ul>{''.join(items)}</ul>")
                    elif child.name == "p":
                        description_parts.append(f"<p>{child.get_text(strip=True)}</p>")
                    elif child.name in ["h1", "h2", "h3", "h4"]:
                        description_parts.append(f"<p><strong>{child.get_text(strip=True)}</strong></p>")

                description = "".join(description_parts)
            else:
                # Fallback: get text from body
                description = body_div.get_text(strip=True)

            # Limit description length
            if len(description) > 3000:
                description = description[:3000] + "..."

            if not description:
                description = f"Clay changelog update for {date_text}"

            # Generate unique ID from title and date
            entry_id = hashlib.md5(f"{title}-{date_text}".encode()).hexdigest()[:12]

            changelog_entries.append({
                "title": title,
                "link": "https://www.clay.com/changelog",
                "description": description,
                "date": date,
                "entry_id": entry_id,
            })

        logger.info(f"Successfully parsed {len(changelog_entries)} changelog entries")
        return changelog_entries

    except Exception as e:
        logger.error(f"Error parsing HTML content: {str(e)}")
        raise


def generate_rss_feed(changelog_entries, feed_name="clay_changelog"):
    """Generate RSS feed from changelog entries."""
    try:
        fg = FeedGenerator()
        fg.title("Clay Changelog")
        fg.description("Product updates and new features from Clay")
        fg.language("en")
        fg.author({"name": "Clay"})
        fg.subtitle("Latest updates from Clay")

        # Set up links correctly (blog URL as main link, not feed URL)
        # Self link first - this becomes <atom:link rel="self">
        fg.link(
            href=f"https://raw.githubusercontent.com/britneyp-revenanas/rss-feeds/main/feeds/feed_{feed_name}.xml",
            rel="self",
        )
        # Alternate link last - this becomes the main <link>
        fg.link(href="https://www.clay.com/changelog", rel="alternate")

        # Sort for correct feed order (newest first in output)
        entries_sorted = sort_posts_for_feed(changelog_entries, date_field="date")

        for entry in entries_sorted:
            fe = fg.add_entry()
            fe.title(entry["title"])
            fe.description(entry["description"])
            fe.link(href=entry["link"])
            fe.published(entry["date"])
            fe.category(term="Changelog")
            fe.id(f"clay-changelog-{entry['entry_id']}")

        logger.info("Successfully generated RSS feed")
        return fg

    except Exception as e:
        logger.error(f"Error generating RSS feed: {str(e)}")
        raise


def save_rss_feed(feed_generator, feed_name="clay_changelog"):
    """Save the RSS feed to a file in the feeds directory."""
    try:
        feeds_dir = get_feeds_dir()
        output_filename = feeds_dir / f"feed_{feed_name}.xml"
        feed_generator.rss_file(str(output_filename), pretty=True)
        logger.info(f"Successfully saved RSS feed to {output_filename}")
        return output_filename
    except Exception as e:
        logger.error(f"Error saving RSS feed: {str(e)}")
        raise


def main(feed_name="clay_changelog"):
    """Main function to generate RSS feed from Clay changelog."""
    try:
        html_content = fetch_changelog_content()
        changelog_entries = parse_changelog_html(html_content)

        if not changelog_entries:
            logger.warning("No changelog entries found!")
            return False

        feed = generate_rss_feed(changelog_entries, feed_name)
        output_file = save_rss_feed(feed, feed_name)

        logger.info(f"Successfully generated RSS feed with {len(changelog_entries)} entries")
        return True

    except Exception as e:
        logger.error(f"Failed to generate RSS feed: {str(e)}")
        return False


if __name__ == "__main__":
    main()
