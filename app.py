from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
import requests
import json
from sqlalchemy import func
from config import Config
import pandas as pd
from sqlalchemy import cast, Integer
from sqlalchemy import desc

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///utm_links.db'
db = SQLAlchemy(app)


class UTMLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(255), nullable=False)
    campaign_content = db.Column(db.String(50), nullable=True)
    campaign_source = db.Column(db.String(50), nullable=False)
    campaign_medium = db.Column(db.String(50), nullable=False)
    campaign_name = db.Column(db.String(50), nullable=False)
    domain = db.Column(db.String(20), nullable=False)
    slug = db.Column(db.String(50), nullable=False)
    short_id = db.Column(db.String(20), nullable=True)
    short_secure_url = db.Column(db.String(20), nullable=True)
    clicks_count = db.Column(db.Integer, default=0)


@app.route('/', methods=['GET', 'POST'])
def index():
    short_secure_url = None
    utm_entries = UTMLink.query.all()
    error_message = None

    if request.method == 'POST':
        url = request.form['url']
        campaign_content = request.form.get('campaign_content', ' ')
        campaign_source = request.form['campaign_source']
        campaign_medium = request.form['campaign_medium']
        campaign_name = request.form['campaign_name']
        domain = request.form['domain']
        slug = request.form.get('slug', "")

        if url == 'other':
            url = request.form['url_other']
        if campaign_content == 'other':
            campaign_content = request.form['campaign_content_other']
        if campaign_source == 'other':
            campaign_source = request.form['campaign_source_other']
        if campaign_medium == 'other':
            campaign_medium = request.form['campaign_medium_other']
        if campaign_name == 'other':
            campaign_name = request.form['campaign_name_other']

        # Construct the UTM link with spaces replaced by '+'
        utm_link = f"{url}?utm_campaign={campaign_name.replace(' ', '+')}&utm_medium={campaign_medium.replace(' ', '+')}&utm_source={campaign_source.replace(' ', '+')}&utm_content={campaign_content.replace(' ', '+')}"

        # Check if a similar record already exists
        existing_record = UTMLink.query.filter_by(
            url=url,
            campaign_content=campaign_content,
            campaign_source=campaign_source,
            campaign_medium=campaign_medium,
            campaign_name=campaign_name,
            domain=domain,
            slug=slug,
        ).first()

        if existing_record:
            error_message = "Similar record already exists."
        else:

            # Create UTM link using Short.io API
            short_url = create_short_link(domain, slug, utm_link)

            if short_url.get('error'):
                # Handle error case (e.g., log the error, display an error message)
                error_message = short_url['error']
                print(f"Error creating short link: {error_message}")
            else:
                # Update the database with short link information
                short_id = short_url['idString']
                short_secure_url = short_url['secureShortURL']
                if slug == "":
                    slug = short_url['path']
                # Save data to the database
                utm_link = UTMLink(
                    url=url, campaign_content=campaign_content, campaign_source=campaign_source,
                    campaign_medium=campaign_medium, campaign_name=campaign_name,
                    domain=domain, slug=slug, short_id=short_id, short_secure_url=short_secure_url
                )

                db.session.add(utm_link)
                db.session.commit()

    # Fetch unique values for dropdowns
    unique_campaign_contents = UTMLink.query.with_entities(UTMLink.campaign_content).distinct().all()
    unique_campaign_sources = UTMLink.query.with_entities(UTMLink.campaign_source).distinct().all()
    unique_campaign_mediums = UTMLink.query.with_entities(UTMLink.campaign_medium).distinct().all()
    unique_campaign_names = UTMLink.query.with_entities(UTMLink.campaign_name).distinct().all()
    unique_url = UTMLink.query.with_entities(UTMLink.url).distinct().all()

    if short_secure_url is None:
        return render_template('index.html', utm_entries=utm_entries, unique_campaign_contents=unique_campaign_contents,
                               unique_campaign_sources=unique_campaign_sources,
                               unique_campaign_mediums=unique_campaign_mediums,
                               unique_campaign_names=unique_campaign_names,
                               unique_url=unique_url, error_message=error_message)
    else:
        return render_template('index.html', utm_entries=utm_entries, unique_campaign_ids=unique_campaign_contents,
                               unique_campaign_sources=unique_campaign_sources,
                               unique_campaign_mediums=unique_campaign_mediums,
                               unique_campaign_names=unique_campaign_names,
                               unique_url=unique_url, short_url=short_secure_url, error_message=error_message)


@app.route('/campaigns', methods=['GET'])
def campaigns():
    # Fetch all records and group them by campaign name
    grouped_campaigns = db.session.query(
        UTMLink.campaign_name,
        func.group_concat(UTMLink.url).label('urls'),
        func.group_concat(UTMLink.campaign_content).label('campaign_contents'),
        func.group_concat(UTMLink.campaign_source).label('campaign_sources'),
        func.group_concat(UTMLink.campaign_medium).label('campaign_mediums'),
        func.group_concat(UTMLink.domain).label('domains'),
        func.group_concat(UTMLink.slug).label('slugs'),
        func.group_concat(UTMLink.short_id).label('short_ids'),
        func.group_concat(UTMLink.short_secure_url).label('short_secure_urls'),
        func.group_concat(UTMLink.clicks_count).label('clicks_counts'),
        func.sum(cast(UTMLink.clicks_count, Integer)).label('total_clicks')
    ).group_by(UTMLink.campaign_name).order_by(desc(UTMLink.id)).all()

    return render_template('campaigns.html', grouped_campaigns=grouped_campaigns)


def update_clicks_count():
    utm_links = UTMLink.query.all()

    for utm_link in utm_links:
        url = f"https://api-v2.short.io/statistics/link/{utm_link.short_id}"
        querystring = {"period": "total", "tzOffset": "0"}

        headers = {
            'accept': "*/*",
            'authorization': 'sk_BNIl8NH1FEMMaVxF'
        }

        response = requests.get(url, headers=headers, params=querystring)

        if response.status_code == 200:
            clicks = response.json().get("humanClicks", 0)
            utm_link.clicks_count = clicks
            db.session.commit()


@app.route('/import', methods=['GET'])
def import_excel_data():
    # Read Excel file into a pandas DataFrame
    df = pd.read_excel("Link.xlsx")

    # Iterate through DataFrame rows and add to the database
    for index, row in df.iterrows():
        utm_link = UTMLink(
            url=row['url'],
            campaign_content=row['campaign_content'],
            campaign_source=row['campaign_source'],
            campaign_medium=row['campaign_medium'],
            campaign_name=row['campaign_name'],
            domain=row['domain'],
            slug=row['slug'],
            short_id=row['short_id'],
            short_secure_url=row['short_secure_url'],
            clicks_count=row["clicks_count"]
        )
        db.session.add(utm_link)

    # Commit changes to the database
    db.session.commit()
    return "Import success"


@app.route('/update-clicks', methods=['GET'])
def update_clicks():
    update_clicks_count()
    return "Clicks count updated!"


def create_short_link(domain, slug, long_url):
    api_url = 'https://api.short.io/links'
    headers = {
        'Content-Type': 'application/json',
        'authorization': Config.SHORT_IO_API_KEY,
    }
    if slug == "":
        data = {
            'originalURL': long_url,
            'domain': domain,
            "title": "ACCZ | API Created"
        }
    else:
        data = {
            'originalURL': long_url,
            'domain': domain,
            'path': slug,
            "title": "ACCZ | API Created"
        }

    response = requests.post(api_url, headers=headers, data=json.dumps(data))
    print(long_url)
    return response.json()


def import_excel_data(file_path):
    # Read Excel file into a pandas DataFrame
    df = pd.read_excel(file_path)

    # Iterate through DataFrame rows and add to the database
    for index, row in df.iterrows():
        utm_link = UTMLink(
            url=row['url'],
            campaign_content=row['campaign_content'],
            campaign_source=row['campaign_source'],
            campaign_medium=row['campaign_medium'],
            campaign_name=row['campaign_name'],
            domain=row['domain'],
            slug=row['slug'],
            short_id=row['short_id'],
            short_secure_url=row['short_secure_url']
        )
        db.session.add(utm_link)

    # Commit changes to the database
    db.session.commit()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)
