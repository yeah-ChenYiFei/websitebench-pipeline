"""Functional, self-contained AMC Theatres WebsiteBench clone."""

from __future__ import annotations

import html
import json
import os
import sqlite3
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.site_backend_integration import open_site_services


SITE_ID = "amc-theatres"
DISPLAY_NAME = "AMC Theatres"
backend, auth = open_site_services()
DB_PATH = Path(backend.lifecycle.database_path)
COOKIE = backend.session_cookie["name"]
LOCAL_COOKIE = "websitebench-amc-theatres-session"
app = FastAPI(title=DISPLAY_NAME)


MOVIES = [
    {"slug": "the-magic-faraway-tree", "title": "The Magic Faraway Tree", "rating": "PG", "runtime": "1 HR 50 MIN", "genre": "Family, Fantasy", "score": 94, "color": "#385c45", "tag": "Now Playing", "desc": "A family discovers a magical tree filled with extraordinary worlds.", "image": "poster-magic-faraway-tree.jpg"},
    {"slug": "the-rivals-of-amziah-king", "title": "The Rivals of Amziah King", "rating": "R", "runtime": "2 HR 10 MIN", "genre": "Drama, Thriller", "score": 92, "color": "#6c4528", "tag": "Now Playing", "desc": "A young woman returns to a rural world of music, loyalty and secrets.", "image": "poster-rivals-amziah-king.jpg"},
    {"slug": "never-stop-chasing", "title": "Never Stop Chasing", "rating": "PG-13", "runtime": "1 HR 58 MIN", "genre": "Drama, Sport", "score": 89, "color": "#375b79", "tag": "Now Playing", "desc": "An athlete finds a new reason to run when the finish line changes.", "image": "poster-never-stop-chasing.jpg"},
    {"slug": "the-brink-of-war", "title": "The Brink of War", "rating": "PG-13", "runtime": "2 HR 6 MIN", "genre": "Drama, Thriller", "score": 87, "color": "#303943", "tag": "Now Playing", "desc": "A tense historical drama about choices made at the edge of conflict.", "image": "poster-brink-of-war.jpg"},
    {"slug": "fast-and-furious-25", "title": "The Fast and the Furious 25th Anniversary", "rating": "PG-13", "runtime": "1 HR 46 MIN", "genre": "Action", "score": 91, "color": "#733728", "tag": "Events", "desc": "The original street-racing adventure returns to the big screen.", "image": "poster-fast-furious-25.jpg"},
    {"slug": "the-odyssey", "title": "The Odyssey", "rating": "PG-13", "runtime": "2 HR 35 MIN", "genre": "Action, Adventure", "score": 97, "color": "#31536f", "tag": "Coming Soon", "desc": "A sweeping voyage home through mythic seas and impossible trials.", "image": "poster-odyssey.jpg"},
    {"slug": "insidious-out-of-the-further", "title": "Insidious: Out of the Further", "rating": "PG-13", "runtime": "1 HR 55 MIN", "genre": "Horror, Thriller", "score": 90, "color": "#241f25", "tag": "Coming Soon", "desc": "A new chapter draws a family back into the darkness beyond.", "image": "poster-insidious.jpg"},
    {"slug": "spider-man-brand-new-day", "title": "Spider-Man: Brand New Day", "rating": "PG-13", "runtime": "2 HR 12 MIN", "genre": "Action, Adventure", "score": 96, "color": "#92322e", "tag": "Coming Soon", "desc": "A friendly neighborhood hero begins a bold new chapter.", "image": "poster-spiderman.jpg"},
    {"slug": "paw-patrol-dino-movie", "title": "PAW Patrol: The Dino Movie", "rating": "PG", "runtime": "1 HR 35 MIN", "genre": "Animation, Family", "score": 88, "color": "#3382aa", "tag": "Coming Soon", "desc": "The pups race into a gigantic prehistoric rescue.", "image": "poster-pawpatrol.jpg"},
    {"slug": "superman", "title": "Superman", "rating": "PG-13", "runtime": "2 HR 9 MIN", "genre": "Action, Adventure", "score": 93, "color": "#1656a0", "tag": "Now Playing", "desc": "A hopeful hero balances his Kryptonian heritage with his human upbringing."},
    {"slug": "jurassic-world-rebirth", "title": "Jurassic World Rebirth", "rating": "PG-13", "runtime": "2 HR 14 MIN", "genre": "Adventure, Thriller", "score": 86, "color": "#1f563a", "tag": "Now Playing", "desc": "An expert team ventures to an isolated equatorial region on a high-stakes mission."},
    {"slug": "f1-the-movie", "title": "F1 The Movie", "rating": "PG-13", "runtime": "2 HR 35 MIN", "genre": "Drama, Sport", "score": 97, "color": "#b51d25", "tag": "Fan Favorite", "desc": "A former racing phenom returns to Formula 1 for one last chance at glory."},
    {"slug": "how-to-train-your-dragon", "title": "How to Train Your Dragon", "rating": "PG", "runtime": "2 HR 5 MIN", "genre": "Family, Fantasy", "score": 95, "color": "#31537b", "tag": "Now Playing", "desc": "A young Viking and a feared dragon form an unlikely friendship."},
    {"slug": "elio", "title": "Elio", "rating": "PG", "runtime": "1 HR 39 MIN", "genre": "Animation, Family", "score": 88, "color": "#6f42a1", "tag": "Now Playing", "desc": "A space-obsessed child is mistaken for Earth's intergalactic ambassador."},
    {"slug": "the-bad-guys-2", "title": "The Bad Guys 2", "rating": "PG", "runtime": "1 HR 44 MIN", "genre": "Animation, Comedy", "score": 91, "color": "#c47220", "tag": "Advance Tickets", "desc": "The reformed crew is pulled into one last globe-trotting heist."},
    {"slug": "the-fantastic-four-first-steps", "title": "The Fantastic Four: First Steps", "rating": "PG-13", "runtime": "1 HR 55 MIN", "genre": "Action, Sci-Fi", "score": 90, "color": "#416a8f", "tag": "Advance Tickets", "desc": "Marvel's first family faces a cosmic threat to their retro-futuristic world."},
    {"slug": "smurfs", "title": "Smurfs", "rating": "PG", "runtime": "1 HR 32 MIN", "genre": "Animation, Comedy", "score": 84, "color": "#3189ce", "tag": "Coming Soon", "desc": "Smurfette leads the crew into the real world to rescue Papa Smurf."},
    {"slug": "teenage-sex-and-death-at-camp-miasma", "title": "Teenage Sex and Death at Camp Miasma", "rating": "R", "runtime": "1 HR 52 MIN", "genre": "Horror, Comedy", "score": 82, "color": "#421f29", "tag": "Now Playing", "desc": "A cult filmmaker returns to the summer camp where her most notorious movie began."},
    {"slug": "spa-weekend", "title": "Spa Weekend", "rating": "R", "runtime": "1 HR 37 MIN", "genre": "Comedy", "score": 86, "color": "#8b6c75", "tag": "Now Playing", "desc": "Four friends discover that a restful getaway can become anything but relaxing."},
    {"slug": "the-end-of-oak-street", "title": "The End of Oak Street", "rating": "PG-13", "runtime": "1 HR 39 MIN", "genre": "Drama, Thriller", "score": 85, "color": "#344452", "tag": "Now Playing", "desc": "Neighbors confront a buried secret when their familiar street begins to change.", "image": "poster-end-oak-street.jpg"},
    {"slug": "mutiny", "title": "Mutiny", "rating": "R", "runtime": "1 HR 35 MIN", "genre": "Action, Thriller", "score": 88, "color": "#223748", "tag": "Now Playing", "desc": "A covert operative must outrun a conspiracy that reaches across every border."},
    {"slug": "tony", "title": "Tony", "rating": "NR", "runtime": "1 HR 46 MIN", "genre": "Documentary", "score": 93, "color": "#4f3427", "tag": "AMC Artisan Films", "desc": "The remarkable origin story of Anthony Bourdain and the kitchen that changed his life."},
    {"slug": "hot-spot", "title": "Hot Spot", "rating": "R", "runtime": "1 HR 41 MIN", "genre": "Drama, Thriller", "score": 83, "color": "#7d3528", "tag": "Now Playing", "desc": "A chance encounter pulls two strangers into a dangerous summer night."},
    {"slug": "city-of-ember-falls", "title": "City of Ember Falls", "rating": "PG-13", "runtime": "1 HR 56 MIN", "genre": "Drama, Mystery", "score": 86, "color": "#59483b", "tag": "Coming Soon", "desc": "A cartographer returns home to trace the lights appearing beneath a mountain town."},
    {"slug": "midnight-on-harbor-line", "title": "Midnight on Harbor Line", "rating": "PG-13", "runtime": "1 HR 48 MIN", "genre": "Mystery, Thriller", "score": 84, "color": "#243d58", "tag": "Coming Soon", "desc": "The final train of the night carries one passenger whose destination does not exist."},
    {"slug": "little-robots-big-sky", "title": "Little Robots, Big Sky", "rating": "PG", "runtime": "1 HR 37 MIN", "genre": "Animation, Family", "score": 91, "color": "#4b83a5", "tag": "Coming Soon", "desc": "A workshop of tiny inventors builds a flying machine to save their valley."},
    {"slug": "northbound-summer", "title": "Northbound Summer", "rating": "PG-13", "runtime": "1 HR 44 MIN", "genre": "Comedy, Drama", "score": 88, "color": "#47745d", "tag": "Coming Soon", "desc": "Two siblings turn a missed flight into a cross-country reunion."},
    {"slug": "paper-moons", "title": "Paper Moons", "rating": "PG", "runtime": "1 HR 42 MIN", "genre": "Family, Fantasy", "score": 89, "color": "#77628c", "tag": "Coming Soon", "desc": "A young artist discovers that every moon she folds opens a doorway."},
    {"slug": "the-astral-garden", "title": "The Astral Garden", "rating": "PG-13", "runtime": "2 HR 4 MIN", "genre": "Adventure, Sci-Fi", "score": 93, "color": "#315f63", "tag": "Coming Soon", "desc": "Explorers find a living conservatory drifting beyond the edge of mapped space."},
    {"slug": "signal-lost", "title": "Signal Lost", "rating": "R", "runtime": "1 HR 51 MIN", "genre": "Sci-Fi, Thriller", "score": 85, "color": "#30374b", "tag": "Coming Soon", "desc": "A radio engineer hears tomorrow's emergency broadcast one night early."},
    {"slug": "second-take", "title": "Second Take", "rating": "PG-13", "runtime": "1 HR 39 MIN", "genre": "Comedy, Romance", "score": 87, "color": "#955d69", "tag": "Coming Soon", "desc": "A documentary crew gets an unexpected chance to redo its most important day."},
    {"slug": "echoes-of-tomorrow", "title": "Echoes of Tomorrow", "rating": "PG-13", "runtime": "2 HR 1 MIN", "genre": "Drama, Sci-Fi", "score": 90, "color": "#4e5678", "tag": "Coming Soon", "desc": "Messages from a future city force one family to reconsider the present."},
    {"slug": "weekend-detectives", "title": "Weekend Detectives", "rating": "PG", "runtime": "1 HR 34 MIN", "genre": "Comedy, Family", "score": 83, "color": "#8a7044", "tag": "Coming Soon", "desc": "Three neighbors investigating a missing bicycle uncover a much bigger mystery."},
    {"slug": "valley-of-fireflies", "title": "Valley of Fireflies", "rating": "PG", "runtime": "1 HR 46 MIN", "genre": "Adventure, Family", "score": 92, "color": "#496c48", "tag": "Coming Soon", "desc": "A camping trip follows a glowing trail into a forgotten nature reserve."},
    {"slug": "the-last-projectionist", "title": "The Last Projectionist", "rating": "PG-13", "runtime": "1 HR 58 MIN", "genre": "Drama", "score": 95, "color": "#694f3e", "tag": "Coming Soon", "desc": "A retiring projectionist prepares one final program for the town that raised him."},
    {"slug": "brightwater", "title": "Brightwater", "rating": "PG-13", "runtime": "1 HR 49 MIN", "genre": "Drama, Mystery", "score": 86, "color": "#316b7a", "tag": "Coming Soon", "desc": "A marine biologist returns to an island where the tides have begun to glow."},
    {"slug": "orbit-school", "title": "Orbit School", "rating": "PG", "runtime": "1 HR 40 MIN", "genre": "Animation, Sci-Fi", "score": 90, "color": "#5a62a1", "tag": "Coming Soon", "desc": "New students learn that the best classroom in space has no ceiling."},
    {"slug": "a-map-of-winter", "title": "A Map of Winter", "rating": "PG-13", "runtime": "1 HR 53 MIN", "genre": "Drama, Adventure", "score": 88, "color": "#566d79", "tag": "Coming Soon", "desc": "An unfinished trail map leads a family through a season of unexpected discoveries."},
    {"slug": "racing-the-sunrise", "title": "Racing the Sunrise", "rating": "PG-13", "runtime": "2 HR 2 MIN", "genre": "Action, Sport", "score": 91, "color": "#9a4c32", "tag": "Coming Soon", "desc": "A rookie endurance driver has one night to earn a place on the grid."},
    {"slug": "lantern-house", "title": "Lantern House", "rating": "PG-13", "runtime": "1 HR 45 MIN", "genre": "Mystery, Fantasy", "score": 89, "color": "#6d5940", "tag": "Coming Soon", "desc": "An old coastal inn lights a room that has been locked for a century."},
]

THEATRES = [
    {"slug": "amc-empire-25", "name": "AMC Empire 25", "city": "New York", "state": "NY", "address": "234 West 42nd Street, New York, New York 10036", "miles": 0.2, "features": ["IMAX", "Dolby Cinema", "AMC Signature Recliners"]},
    {"slug": "amc-34th-street-14", "name": "AMC 34th Street 14", "city": "New York", "state": "NY", "address": "312 W 34th St, New York, New York 10001", "miles": 0.7, "features": ["Reserved Seating", "Laser at AMC"]},
    {"slug": "amc-lincoln-square-13", "name": "AMC Lincoln Square 13", "city": "New York", "state": "NY", "address": "1998 Broadway, New York, New York 10023", "miles": 1.1, "features": ["IMAX 70mm", "Dolby Cinema"]},
    {"slug": "amc-village-7", "name": "AMC Village 7", "city": "New York", "state": "NY", "address": "66 Third Ave, New York, New York 10003", "miles": 2.0, "features": ["AMC Signature Recliners", "Open Caption"]},
    {"slug": "amc-century-city-15", "name": "AMC Century City 15", "city": "Los Angeles", "state": "CA", "address": "10250 Santa Monica Blvd, Los Angeles, California 90067", "miles": 3.2, "features": ["IMAX", "Dolby Cinema", "Dine-In Delivery"]},
    {"slug": "amc-river-east-21", "name": "AMC River East 21", "city": "Chicago", "state": "IL", "address": "322 E Illinois St, Chicago, Illinois 60611", "miles": 0.8, "features": ["IMAX", "Reserved Seating"]},
]

SHOWTIMES = ["10:30 AM", "12:15 PM", "1:40 PM", "3:25 PM", "5:10 PM", "7:00 PM", "8:45 PM", "10:15 PM"]
POSTER_IMAGES = [
    "poster-magic-faraway-tree.jpg", "poster-rivals-amziah-king.jpg",
    "poster-pawpatrol.jpg", "poster-odyssey.jpg", "poster-never-stop-chasing.jpg",
    "poster-insidious.jpg", "poster-spiderman.jpg", "poster-end-oak-street.jpg",
    "poster-fast-furious-25.jpg",
]
OFFER_ITEMS = [
    ("Special Offers & Events", "A Legacy of Handcrafted Animation", "A season of beloved animated classics returns to the big screen.", "promo-tony.jpg", "Get Tickets", "/showtimes"),
    ("Special Offers & Events", "Watch a Surprise Movie First", "AMC Screen Unseen brings a never-before-seen title to a local showtime.", "promo-super-troopers.jpg", "Learn More", "/movies"),
    ("Special Offers & Events", "Host a Private Theatre Rental", "Bring friends and family together for a private big-screen event.", "theatre-hero-desktop.avif", "Book Now", "/group-events"),
    ("AMC Stubs Exclusives", "Get 50% off Tickets Two Days a Week", "Join AMC Stubs Insider for local member benefits on Tuesdays and Wednesdays.", "hero-stubs-desktop.jpg", "Join for Free", "/sign-up?plan=insider"),
    ("AMC Stubs Exclusives", "Sign in for Points & Perks", "Keep rewards, favorites and sandbox ticket history together in My AMC.", "stubs-bg-insider.jpg", "Sign In", "/login"),
    ("Food & Drink", "Snack and Sip All Summer Long", "Pair a small popcorn with a refreshing fountain drink before the feature.", "promo-snack-sip.jpg", "Get Offer", "/food-and-drink/snack-and-sip"),
    ("Food & Drink", "Float Away with a New Classic", "Try the bright cherry-cola float flavor featured at the concession stand.", "promo-cherry-coke.jpg", "Order Now", "/food-and-drink/cherry-cola-float"),
    ("Discounts", "Enjoy Discount Matinees Any Day", "Plan an earlier showtime and review the available local ticket options.", "showtime-video.jpg", "See Showtimes", "/showtimes"),
    ("Discounts", "Students Always Save at AMC", "Review participating-theatre information before planning your visit.", "theatre-bg.avif", "Plan Your Visit", "/movie-theatres"),
]
FOOD_ITEMS = [
    ("perfectly-popcorn", "AMC Perfectly Popcorn", "Freshly popped at AMC with classic buttery flavor and shareable sizes.", "promo-popcorn-pass.jpg"),
    ("dine-in", "AMC DINE-IN", "A movie theatre and restaurant experience with food delivered to your seat.", "promo-snack-sip.jpg"),
    ("classic-concessions", "AMC CLASSIC Concessions", "Movie-night favorites including popcorn, candy and fountain drinks.", "promo-cherry-coke.jpg"),
    ("collectibles", "Concession Collectibles", "Limited movie-themed vessels and collectibles available while supplies last.", "promo-pawpatrol-collectibles.jpg"),
    ("macguffins", "MacGuffins Bar", "Beer, wine and cocktails before the movie and during the show at select theatres.", "promo-super-troopers.jpg"),
    ("snack-and-sip", "Snack and Sip", "A popcorn-and-drink combination made for a summer movie getaway.", "promo-snack-sip.jpg"),
    ("cherry-cola-float", "Cherry Cola Float ICEE", "A cold cherry-cola float flavor for the concession stand.", "promo-cherry-coke.jpg"),
]
DIRECTORY_MARKETS = [
    ('Albany, GA', '/movie-theatres/albany-ga'),
    ('Albuquerque, NM', '/movie-theatres/albuquerque-nm'),
    ('Allentown', '/movie-theatres/allentown'),
    ('Altoona, PA', '/movie-theatres/altoona-pa'),
    ('Atlanta', '/movie-theatres/atlanta'),
    ('Austin', '/movie-theatres/austin'),
    ('Bakersfield', '/movie-theatres/bakersfield'),
    ('Baltimore', '/movie-theatres/baltimore'),
    ('Baton Rouge', '/movie-theatres/baton-rouge'),
    ('Billings, MT', '/movie-theatres/billings-mt'),
    ('Binghamton', '/movie-theatres/binghamton'),
    ('Birmingham, AL', '/movie-theatres/birmingham-al'),
    ('Bloomington - IL', '/movie-theatres/bloomington-il'),
    ('Bloomington - IN', '/movie-theatres/bloomington-in'),
    ('Boston', '/movie-theatres/boston'),
    ('Brick', '/movie-theatres/brick'),
    ('Bridgewater', '/movie-theatres/bridgewater'),
    ('Brownsville', '/movie-theatres/brownsville'),
    ('Buffalo', '/movie-theatres/buffalo'),
    ('Carbondale', '/movie-theatres/carbondale'),
    ('Charlotte', '/movie-theatres/charlotte'),
    ('Chattanooga, TN', '/movie-theatres/chattanooga-tn'),
    ('Chicago', '/movie-theatres/chicago'),
    ('Cincinnati', '/movie-theatres/cincinnati'),
    ('Cleveland', '/movie-theatres/cleveland'),
    ('Clifton', '/movie-theatres/clifton'),
    ('Colorado Springs, CO', '/movie-theatres/colorado-springs-co'),
    ('Columbia', '/movie-theatres/columbia'),
    ('Columbus, GA', '/movie-theatres/columbus-ga'),
    ('Columbus', '/movie-theatres/columbus'),
    ('Corpus Christi', '/movie-theatres/corpus-christi'),
    ('Dallas / Ft. Worth', '/movie-theatres/dallas-ft-worth'),
    ('Danbury', '/movie-theatres/danbury'),
    ('Denver', '/movie-theatres/denver'),
    ('Destin', '/movie-theatres/destin'),
    ('Detroit', '/movie-theatres/detroit'),
    ('Dothan, AL', '/movie-theatres/dothan-al'),
    ('Dubuque', '/movie-theatres/dubuque'),
    ('East Brunswick', '/movie-theatres/east-brunswick'),
    ('East Hanover', '/movie-theatres/east-hanover'),
    ('Eatontown', '/movie-theatres/eatontown'),
    ('Edison', '/movie-theatres/edison'),
    ('El Paso', '/movie-theatres/el-paso'),
    ('Elizabeth', '/movie-theatres/elizabeth'),
    ('Eugene, OR', '/movie-theatres/eugene-or'),
    ('Evansville', '/movie-theatres/evansville'),
    ('Fayetteville', '/movie-theatres/fayetteville'),
    ('Fort Myers', '/movie-theatres/fort-myers'),
    ('Freehold', '/movie-theatres/freehold'),
    ('Ft. Wayne, IN', '/movie-theatres/ft-wayne-in'),
    ('Galesburg', '/movie-theatres/galesburg'),
    ('Gary', '/movie-theatres/gary'),
    ('Grand Rapids', '/movie-theatres/grand-rapids'),
    ('Great Falls, MT', '/movie-theatres/great-falls-mt'),
    ('Green Bay, WI', '/movie-theatres/green-bay-wi'),
    ('Greensboro, NC', '/movie-theatres/greensboro-nc'),
    ('Greenville, NC', '/movie-theatres/greenville-nc'),
    ('Hackensack', '/movie-theatres/hackensack'),
    ('Harrisburg, PA', '/movie-theatres/harrisburg-pa'),
    ('Hartford-New Haven', '/movie-theatres/hartford-new-haven'),
    ('Houston', '/movie-theatres/houston'),
    ('Huntsville, AL', '/movie-theatres/huntsville-al'),
    ('Idaho Falls, ID', '/movie-theatres/idaho-falls-id'),
    ('Indianapolis', '/movie-theatres/indianapolis'),
    ('Jacksonville', '/movie-theatres/jacksonville'),
    ('Jersey City', '/movie-theatres/jersey-city'),
    ('Kansas City', '/movie-theatres/kansas-city'),
    ('Knoxville, TN', '/movie-theatres/knoxville-tn'),
    ('Kokomo', '/movie-theatres/kokomo'),
    ('Lake Delton', '/movie-theatres/lake-delton'),
    ('Las Vegas', '/movie-theatres/las-vegas'),
    ('Leesburg', '/movie-theatres/leesburg'),
    ('Linden', '/movie-theatres/linden'),
    ('Little Rock, AR', '/movie-theatres/little-rock-ar'),
    ('Los Angeles', '/movie-theatres/los-angeles'),
    ('Louisville, KY', '/movie-theatres/louisville-ky'),
    ('Madison', '/movie-theatres/madison'),
    ('Miami / Ft. Lauderdale', '/movie-theatres/miami-ft-lauderdale'),
    ('Middletown', '/movie-theatres/middletown'),
    ('Milwaukee', '/movie-theatres/milwaukee'),
    ('Minneapolis / St. Paul', '/movie-theatres/minneapolis-st-paul'),
    ('Minot, ND', '/movie-theatres/minot-nd'),
    ('Miramar Beach, FL', '/movie-theatres/miramar-beach-fl'),
    ('Missoula, MT', '/movie-theatres/missoula-mt'),
    ('Montgomery', '/movie-theatres/montgomery'),
    ('Morristown', '/movie-theatres/morristown'),
    ('Mountainside', '/movie-theatres/mountainside'),
    ('Muncie/Richmond', '/movie-theatres/muncie-richmond'),
    ('Myrtle Beach, SC', '/movie-theatres/myrtle-beach-sc'),
    ('Nashville, TN', '/movie-theatres/nashville-tn'),
    ('New Brunswick', '/movie-theatres/new-brunswick'),
    ('New Orleans', '/movie-theatres/new-orleans'),
    ('New York City', '/movie-theatres/new-york-city'),
    ('Norfolk', '/movie-theatres/norfolk'),
    ('Oakland', '/movie-theatres/oakland'),
    ('Oklahoma City', '/movie-theatres/oklahoma-city'),
    ('Omaha', '/movie-theatres/omaha'),
    ('Orlando / Daytona Beach', '/movie-theatres/orlando-daytona-beach'),
    ('Paramus', '/movie-theatres/paramus'),
    ('Pensacola/Mobile', '/movie-theatres/pensacola-mobile'),
    ('Peoria', '/movie-theatres/peoria'),
    ('Philadelphia', '/movie-theatres/philadelphia'),
    ('Phoenix', '/movie-theatres/phoenix'),
    ('Pittsburgh', '/movie-theatres/pittsburgh'),
    ('Plainville', '/movie-theatres/plainville'),
    ('Poplar Bluff', '/movie-theatres/poplar-bluff'),
    ('Port Chester', '/movie-theatres/port-chester'),
    ('Quincy', '/movie-theatres/quincy'),
    ('Raleigh - Durham', '/movie-theatres/raleigh-durham'),
    ('Rapid City, SD', '/movie-theatres/rapid-city-sd'),
    ('Richmond, VA', '/movie-theatres/richmond-va'),
    ('Ridgefield Park', '/movie-theatres/ridgefield-park'),
    ('Roanoke, VA', '/movie-theatres/roanoke-va'),
    ('Rochester', '/movie-theatres/rochester'),
    ('Rockaway', '/movie-theatres/rockaway'),
    ('Rockford', '/movie-theatres/rockford'),
    ('Salt Lake City', '/movie-theatres/salt-lake-city'),
    ('San Antonio', '/movie-theatres/san-antonio'),
    ('San Diego', '/movie-theatres/san-diego'),
    ('San Francisco', '/movie-theatres/san-francisco'),
    ('San Jose', '/movie-theatres/san-jose'),
    ('Saratoga Springs', '/movie-theatres/saratoga-springs'),
    ('Savannah, GA', '/movie-theatres/savannah-ga'),
    ('Seattle / Tacoma', '/movie-theatres/seattle-tacoma'),
    ('Sherman, TX', '/movie-theatres/sherman-tx'),
    ('Sioux City, IA', '/movie-theatres/sioux-city-ia'),
    ('South Bend', '/movie-theatres/south-bend'),
    ('Spokane', '/movie-theatres/spokane'),
    ('Springfield - IL', '/movie-theatres/springfield-il'),
    ('Springfield - MO', '/movie-theatres/springfield-mo'),
    ('St. Louis', '/movie-theatres/st-louis'),
    ('Tallahassee', '/movie-theatres/tallahassee'),
    ('Tampa / St. Petersburg', '/movie-theatres/tampa-st-petersburg'),
    ('Terre Haute', '/movie-theatres/terre-haute'),
    ('Toledo, OH', '/movie-theatres/toledo-oh'),
    ('Topeka, KS', '/movie-theatres/topeka-ks'),
    ('Traverse City, MI', '/movie-theatres/traverse-city-mi'),
    ('Tri-Cities, TN', '/movie-theatres/tri-cities-tn'),
    ('Tucson', '/movie-theatres/tucson'),
    ('Tulsa', '/movie-theatres/tulsa'),
    ('Tyler, TX', '/movie-theatres/tyler-tx'),
    ('Vernon Hills', '/movie-theatres/vernon-hills'),
    ('Vero Beach', '/movie-theatres/vero-beach'),
    ('Waco', '/movie-theatres/waco'),
    ('Washington D.C.', '/movie-theatres/washington-d-c'),
    ('Wayne', '/movie-theatres/wayne'),
    ('West Hills', '/movie-theatres/west-hills'),
    ('West Nyack', '/movie-theatres/west-nyack'),
    ('West Orange', '/movie-theatres/west-orange'),
    ('West Palm Beach', '/movie-theatres/west-palm-beach'),
    ('Wichita Falls, TX', '/movie-theatres/wichita-falls-tx'),
    ('Wichita', '/movie-theatres/wichita'),
    ('Wilkes Barre, PA', '/movie-theatres/wilkes-barre-pa'),
    ('Yakima, WA', '/movie-theatres/yakima-wa'),
]


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_site_schema() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS amc_favorites (
              session_token TEXT NOT NULL,
              movie_slug TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY(session_token, movie_slug)
            );
            CREATE TABLE IF NOT EXISTS amc_orders (
              order_id TEXT PRIMARY KEY,
              session_token TEXT NOT NULL,
              movie_slug TEXT NOT NULL,
              theatre_slug TEXT NOT NULL,
              showtime TEXT NOT NULL,
              seats_json TEXT NOT NULL,
              total_cents INTEGER NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS amc_order_metadata (
              order_id TEXT PRIMARY KEY,
              shared_with TEXT NOT NULL DEFAULT '',
              reminder_enabled INTEGER NOT NULL DEFAULT 0,
              concessions_json TEXT NOT NULL DEFAULT '[]',
              notes TEXT NOT NULL DEFAULT '',
              promo_code TEXT NOT NULL DEFAULT '',
              FOREIGN KEY(order_id) REFERENCES amc_orders(order_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS amc_reviews (
              order_id TEXT PRIMARY KEY,
              rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
              body TEXT NOT NULL DEFAULT '',
              visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','public')),
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(order_id) REFERENCES amc_orders(order_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS amc_preferences (
              session_token TEXT PRIMARY KEY,
              preferred_theatre TEXT NOT NULL DEFAULT 'amc-empire-25',
              notifications_enabled INTEGER NOT NULL DEFAULT 0,
              privacy_mode TEXT NOT NULL DEFAULT 'standard',
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS amc_memberships (
              session_token TEXT PRIMARY KEY,
              plan TEXT NOT NULL DEFAULT 'insider',
              status TEXT NOT NULL DEFAULT 'selected',
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        order_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(amc_orders)")
        }
        for column, declaration in {
            "ticket_type": "TEXT NOT NULL DEFAULT 'Adult'",
            "format_name": "TEXT NOT NULL DEFAULT 'Standard'",
            "attendee_name": "TEXT NOT NULL DEFAULT 'Local Guest'",
        }.items():
            if column not in order_columns:
                connection.execute(
                    f"ALTER TABLE amc_orders ADD COLUMN {column} {declaration}"
                )
    if not auth.account_exists("guest@example.com"):
        auth.seed_account(subject_id="amc-demo-member", email="guest@example.com", display_name="AMC Guest", password="demo12345", email_verified=True)


initialize_site_schema()


SYNTHETIC_ACCOUNT = {
    "subject_id": "amc-demo-member",
    "email": "guest@example.com",
    "display_name": "AMC Guest",
    "password": "demo12345",
    "email_verified": True,
}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def movie(slug: str) -> dict[str, Any] | None:
    return next((item for item in MOVIES if item["slug"] == slug), None)


def theatre(slug: str) -> dict[str, Any] | None:
    return next((item for item in THEATRES if item["slug"] == slug), None)


def cookie_name(request: Request) -> str:
    return COOKIE if request.url.scheme == "https" else LOCAL_COOKIE


def session(request: Request) -> tuple[str, dict[str, Any]]:
    return auth.ensure_session(request.cookies.get(cookie_name(request)))


def with_session(response: HTMLResponse | JSONResponse | RedirectResponse, token: str, request: Request) -> Any:
    name = cookie_name(request)
    if request.cookies.get(name) != token:
        response.set_cookie(name, token, httponly=True, secure=request.url.scheme == "https", samesite="lax", path="/")
    return response


def rotate_site_state(connection: sqlite3.Connection, old_token: str, new_token: str) -> None:
    """Carry anonymous clone state to the authenticated account owner."""

    account = connection.execute(
        "SELECT accounts.subject_id FROM local_auth_sessions AS sessions "
        "JOIN local_auth_accounts AS accounts ON accounts.account_id=sessions.account_id "
        "WHERE sessions.session_digest=?",
        (new_token,),
    ).fetchone()
    new_owner = f"account:{account['subject_id']}" if account is not None else new_token

    connection.execute(
        "UPDATE OR IGNORE amc_favorites SET session_token=? WHERE session_token=?",
        (new_owner, old_token),
    )
    connection.execute(
        "DELETE FROM amc_favorites WHERE session_token=?",
        (old_token,),
    )
    connection.execute(
        "UPDATE amc_orders SET session_token=? WHERE session_token=?",
        (new_owner, old_token),
    )
    connection.execute(
        "UPDATE OR REPLACE amc_preferences SET session_token=? WHERE session_token=?",
        (new_owner, old_token),
    )
    connection.execute(
        "UPDATE OR REPLACE amc_memberships SET session_token=? WHERE session_token=?",
        (new_owner, old_token),
    )


def site_owner(
    connection: sqlite3.Connection,
    token: str,
    state: dict[str, Any] | None = None,
) -> str:
    """Return a session owner for guests or a stable auth subject for accounts."""

    session_digest = auth.session_owner_digest(token)
    resolved = state if state is not None else auth.resolve_session(token)
    account = (resolved or {}).get("account") or {}
    subject_id = account.get("subject_id")
    if not subject_id:
        return session_digest
    owner = f"account:{subject_id}"
    # Compatibility for state written by an already-authenticated session before
    # stable subject ownership was introduced.
    rotate_site_state(connection, session_digest, owner)
    return owner


def user_label(state: dict[str, Any]) -> str:
    account_state = state.get("account") or {}
    return esc(account_state.get("display_name") or "Sign In")


def layout(title: str, body: str, state: dict[str, Any], *, active: str = "") -> str:
    signed_in = bool(state.get("authenticated"))
    account_href = "/account" if signed_in else "/login"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | AMC Theatres</title><link rel="stylesheet" href="/assets/amc.css"></head>
<body><a class="skip" href="#main">Skip to main content</a>
<div class="alert-strip"><span class="alert-copy"><a href="/food-and-drink">Buy</a> the 2026 AMC Popcorn Pass™ for the new low price of $17.99 &amp; <strong>get 50% off a daily large popcorn</strong>.</span><button class="alert-close" type="button" aria-label="Dismiss alert"><img src="/local-icons/close.svg" alt=""></button></div>
<header><div class="wrap nav"><div class="mobile-tools"><button class="mobile-menu icon-button" data-menu aria-label="Open navigation" aria-expanded="false"><span class="menu-lines"><i></i><i></i><i></i></span></button><button class="mobile-search icon-button" data-open-search aria-label="Search"><img src="/local-icons/search.svg" alt=""></button></div><a class="logo" href="/" aria-label="AMC Theatres home"><img src="/local-icons/logo.svg" alt="AMC Theatres"><span>amc<small>THEATRES</small></span></a>
<nav aria-label="Primary"><a class="{'on' if active == 'movies' else ''}" href="/movies">See a Movie</a><a class="{'on' if active == 'theatres' else ''}" href="/movie-theatres">Find a Theatre</a><a href="/food-and-drink">Food &amp; Drinks</a><a class="{'on' if active == 'more' else ''}" href="/more">More</a></nav>
<form class="header-search" action="/search"><label class="sr-only" for="header-q">Search AMC</label><input id="header-q" name="q" placeholder="Search"><button aria-label="Submit search"><img src="/local-icons/search-muted.svg" alt=""></button></form><div class="nav-actions"><a class="showtimes-link" href="/showtimes"><img src="/local-icons/showtimes.svg" alt=""><span>Showtimes</span></a><a class="account" href="{account_href}" aria-label="My AMC account"><img src="/local-icons/account.svg" alt=""><span>{user_label(state)}</span><img class="account-chevron" src="/local-icons/chevron-white.svg" alt=""></a></div></div></header>
<div class="subnav"><div class="wrap"><a class="theatre-location" href="/movie-theatres"><img src="/local-icons/location.svg" alt="">AMC Demo Theatre</a><a class="sub-get-tickets" href="/showtimes">Get Tickets<img src="/local-icons/chevron-blue.svg" alt=""></a><span></span><a href="/group-events">Group Events</a><a href="/merchandise">Merchandise</a><a href="/gift-cards">Gift Cards</a><a href="/offers">Offers</a><a href="/on-demand">On Demand</a></div></div><div id="search-panel" class="search-panel" hidden><form action="/search"><label for="global-q">Search movies and theatres</label><div><input id="global-q" name="q" placeholder="Movie or theatre" autofocus><button>Search</button></div></form></div>
<main id="main">{body}</main>
<footer><div class="wrap footer-grid"><div><div class="logo small"><span>amc<small>THEATRES</small></span></div><p>Make movies more rewarding.</p></div><div><h3>Movies</h3><a href="/movies">Now Playing</a><a href="/movies?sort=Featured">Coming Soon</a><a href="/showtimes">Showtimes</a></div><div><h3>Theatres</h3><a href="/movie-theatres">Find a Theatre</a><a href="/movie-theatres/ny/amc-empire-25">AMC Empire 25</a><a href="/help">Premium Offerings</a></div><div><h3>AMC Stubs</h3><a href="/sign-up">Join AMC Stubs</a><a href="/account">My AMC</a><a href="/track-order">Track an Order</a><a href="/help">Help Center</a></div></div><p class="copyright">WebsiteBench offline clone · Fully local · No real purchases are processed.</p></footer>
<div id="toast" role="status" aria-live="polite"></div><script src="/assets/amc.js"></script></body></html>"""


def poster_image(item: dict[str, Any]) -> str:
    if item.get("image"):
        return item["image"]
    return POSTER_IMAGES[sum(ord(char) for char in item["slug"]) % len(POSTER_IMAGES)]


def poster_card(item: dict[str, Any], favorite: bool = False, *, home: bool = False) -> str:
    action = "Remove" if favorite else "Save"
    suffix = " from saved movies" if favorite else ""
    style = f"background-image:linear-gradient(0deg,#0009,#0000 58%),url('/local-assets/{esc(poster_image(item))}')"
    home_attrs = f' data-movie-category="{esc(item["tag"])}"' if home else ""
    hidden = " hidden" if home and item["tag"] != "Now Playing" else ""
    return f"""<article class="movie-card"{home_attrs}{hidden}><a class="poster" style="{style}" href="/movies/{esc(item['slug'])}"><span class="poster-kicker">AMC</span><strong>{esc(item['title'])}</strong><small>{esc(item['tag'])}</small></a><div class="card-copy"><p class="eyebrow">{esc(item['rating'])} · {esc(item['runtime'])}</p><h3><a href="/movies/{esc(item['slug'])}">{esc(item['title'])}</a></h3><div class="card-actions"><a class="button compact" href="/showtimes?movie={esc(item['slug'])}">Get Tickets</a><button class="heart {'saved' if favorite else ''}" data-favorite="{esc(item['slug'])}" data-title="{esc(item['title'])}" aria-pressed="{'true' if favorite else 'false'}" aria-label="{action} {esc(item['title'])}{suffix}">♥</button></div></div></article>"""


LISTING_META = {
    "insidious-out-of-the-further": ("1 HR 45 MIN", "PG13", "Released August 21, 2026"),
    "spider-man-brand-new-day": ("2 HR 24 MIN", "PG13", "Released July 31, 2026"),
    "the-odyssey": ("2 HR 52 MIN", "R", "Released July 17, 2026"),
    "paw-patrol-dino-movie": ("1 HR 28 MIN", "PG", "Released August 14, 2026"),
    "the-end-of-oak-street": ("1 HR 39 MIN", "PG13", "Released August 14, 2026"),
}


def movie_listing_card(item: dict[str, Any], favorite: bool = False) -> str:
    runtime, rating, release = LISTING_META.get(
        item["slug"], (item["runtime"], item["rating"].replace("-", ""), "Now Playing")
    )
    image = f"background-image:url('/local-assets/{esc(poster_image(item))}')"
    action = "Remove" if favorite else "Save"
    return f"""<article class="movie-listing-card"><a class="listing-poster" style="{image}" href="/movies/{esc(item['slug'])}" aria-label="Open {esc(item['title'])}"></a><h3><a href="/movies/{esc(item['slug'])}">{esc(item['title'])}</a></h3><ul class="listing-meta"><li><span class="listing-runtime-info"><span>{esc(runtime)}</span><span class="listing-info" aria-label="More Info"><svg viewBox="0 0 45 45" aria-hidden="true"><path d="M22.5 45C10.125 45 0 34.875 0 22.5S10.125 0 22.5 0 45 10.125 45 22.5 34.875 45 22.5 45m0-41.625c-10.35 0-18.9 8.55-18.9 18.9s8.55 18.9 18.9 18.9 18.9-8.55 18.9-18.9-8.55-18.9-18.9-18.9"></path></svg></span></span></li><li><span>{esc(rating)}</span></li></ul><p class="listing-release">{esc(release)}</p><div class="listing-actions"><a class="button" href="/showtimes?movie={esc(item['slug'])}">Get Tickets</a><button class="heart {'saved' if favorite else ''}" data-favorite="{esc(item['slug'])}" data-title="{esc(item['title'])}" aria-pressed="{'true' if favorite else 'false'}" aria-label="{action} {esc(item['title'])}">♥</button></div></article>"""


def favorite_slugs(token: str) -> set[str]:
    with db() as connection:
        owner = site_owner(connection, token)
        return {row[0] for row in connection.execute("SELECT movie_slug FROM amc_favorites WHERE session_token=?", (owner,))}


@app.get("/healthz")
def healthz() -> JSONResponse:
    with db() as connection:
        connection.execute("SELECT 1").fetchone()
    return JSONResponse(
        {
            "ok": True,
            "site_id": SITE_ID,
            "backend": "sqlite",
            "payment_adapter": "local-sandbox",
        },
        headers={
            "X-WebsiteBench-Container-Build-ID": os.environ.get(
                "DEPLOYMENT_BUILD_ID", os.environ.get("SOURCE_REF", "")
            )
        },
    )


@app.get("/assets/amc.css")
def css() -> HTMLResponse:
    return HTMLResponse(CSS, media_type="text/css")


@app.get("/assets/amc.js")
def js() -> HTMLResponse:
    return HTMLResponse(JS, media_type="application/javascript")


@app.get("/local-assets/{filename}")
def local_asset(filename: str) -> FileResponse:
    allowed = {
        "hero-insidious.jpg", "hero-exact.avif", "hero-insidious-mobile.jpg", "hero-stubs-desktop.jpg", "hero-stubs-mobile.jpg", "movies-bg.jpg", "movies-exact.avif", "poster-insidious.jpg",
        "poster-odyssey.jpg", "poster-pawpatrol.jpg", "poster-spiderman.jpg",
        "poster-magic-faraway-tree.jpg", "poster-rivals-amziah-king.jpg",
        "poster-never-stop-chasing.jpg", "poster-brink-of-war.jpg",
        "poster-fast-furious-25.jpg", "poster-end-oak-street.jpg", "promo-pawpatrol-collectibles.jpg",
        "showtime-insidious.jpg", "showtime-spiderman.jpg", "showtime-odyssey.png", "showtime-pawpatrol.jpg",
        "showtime-video.jpg",
        "stubs-bg-insider.jpg", "stubs-bg-premiere.jpg", "stubs-bg-alist.jpg",
        "stubs-logo-insider.png", "stubs-logo-premiere.png", "stubs-logo-alist.png",
        "help-hero.avif",
        "help-hero-mobile.avif",
        "theatre-hero-desktop.avif", "theatre-hero-mobile.avif", "theatre-bg.avif",
        "theatre-poster-it-ends.avif", "theatre-poster-oak.avif", "theatre-poster-odyssey.avif",
        "theatre-poster-paw.avif", "theatre-poster-irumudi.avif",
        "promo-snack-sip.jpg", "promo-popcorn-pass.jpg", "promo-tony.jpg",
        "promo-cherry-coke.jpg", "promo-super-troopers.jpg",
    }
    if filename not in allowed:
        raise StarletteHTTPException(status_code=404)
    media_type = "image/avif" if filename.endswith(".avif") else "image/png" if filename.endswith(".png") else "image/jpeg"
    return FileResponse(Path(__file__).parent / "static" / "source" / filename, media_type=media_type)


@app.get("/local-fonts/{filename}")
def local_font(filename: str) -> FileResponse:
    allowed = {
        "gordita-regular.woff2", "gordita-medium.woff2",
        "gordita-bold.woff2", "gordita-black.woff2",
    }
    if filename not in allowed:
        raise StarletteHTTPException(status_code=404)
    return FileResponse(
        Path(__file__).parent / "static" / "source" / filename,
        media_type="font/woff2",
    )


@app.get("/local-icons/{filename}")
def local_icon(filename: str) -> FileResponse:
    if filename not in {
        "account.svg", "chevron-blue.svg", "chevron-white.svg", "close.svg", "location.svg", "logo.svg",
        "search.svg", "search-muted.svg", "showtimes.svg",
    }:
        raise StarletteHTTPException(status_code=404)
    return FileResponse(
        Path(__file__).parent / "static" / "source" / filename,
        media_type="image/svg+xml",
    )


@app.get("/favicon.ico")
def favicon() -> Response:
    icon = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="30" fill="#d71920"/><text x="32" y="39" text-anchor="middle" font-family="Arial" font-size="22" font-weight="700" fill="white">amc</text></svg>'
    return Response(icon, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    token, state = session(request)
    favorites = favorite_slugs(token)
    home_slugs = [
        "the-magic-faraway-tree", "the-rivals-of-amziah-king", "never-stop-chasing",
        "the-brink-of-war", "the-end-of-oak-street", "fast-and-furious-25",
        "the-odyssey", "insidious-out-of-the-further", "spider-man-brand-new-day",
        "paw-patrol-dino-movie", "smurfs",
    ]
    home_movies = [movie(slug) for slug in home_slugs]
    cards = "".join(poster_card(item, item["slug"] in favorites, home=True) for item in home_movies if item is not None)
    dots = "".join(f'<button class="dot {"on" if index == 0 else ""}" data-slide="{index}" aria-label="Promotion {index + 1}" aria-pressed="{"true" if index == 0 else "false"}"></button>' for index in range(9))
    body = f"""<section class="hero" data-carousel><div class="wrap hero-content"><div class="hero-grid"><header><p class="eyebrow light">AMC STUBS MEMBER EXCLUSIVE</p><h2 class="hero-title">Get 50% off* Tickets Two Days a Week</h2></header><div class="hero-description"><span>Join Insider for free and save on your Tuesday or Wednesday movie getaways.</span><p class="hero-footnote"><span>*50% off discount applied to the adult evening base ticket price.</span></p></div><div class="hero-actions"><a class="button hero-button" href="/sign-up?plan=insider">Join for Free</a><a class="hero-learn" href="/offers">Learn More</a></div></div></div><div class="carousel-controls"><button data-slide="prev" aria-label="Previous promotion">‹</button>{dots}<button data-slide="next" aria-label="Next promotion">›</button></div></section>
<section class="movies-home"><div class="wrap"><div class="movies-title"><h2>Movies at AMC</h2><div role="tablist"><button class="on" role="tab" aria-selected="true" data-movie-tab="Now Playing">Now Playing</button><button role="tab" aria-selected="false" data-movie-tab="Events">Events</button><button role="tab" aria-selected="false" data-movie-tab="Coming Soon">Coming Soon</button></div></div><div class="movie-rail">{cards}</div><a class="button rail-more" href="/movies">See All Movies</a></div></section>
<section class="app-promo"><div class="wrap app-grid"><div><p class="eyebrow light">Movies are better with the app</p><h2>Your next movie night, in your pocket.</h2></div><div><p>Find showtimes, save favorites and keep local sandbox tickets together.</p><a class="button white" href="/sign-up">Join AMC Stubs</a></div></div></section>
<section class="home-promotion"><div class="promotion-image" style="background-image:url('/local-assets/promo-pawpatrol-collectibles.jpg')"></div><div class="promotion-copy"><p class="eyebrow red">Only at AMC</p><h2>Collect Yours Before They Are Extinct</h2><p>Make family movie day bigger with a limited local showcase of theatre collectibles.</p><a class="button" href="/movies/paw-patrol-dino-movie">Explore the movie</a></div></section>
<section class="home-promotion reverse"><div class="promotion-image" style="background-image:url('/local-assets/promo-snack-sip.jpg')"></div><div class="promotion-copy"><p class="eyebrow red">Summer at AMC</p><h2>Snack and Sip All Summer Long</h2><p>Pair the big screen with a refreshing local concession showcase.</p><a class="button" href="/showtimes">Find a showtime</a></div></section>
<section class="home-promotion"><div class="promotion-image" style="background-image:url('/local-assets/promo-popcorn-pass.jpg')"></div><div class="promotion-copy"><p class="eyebrow red">More movie nights</p><h2>This Big Poppin Deal Just Got Better</h2><p>Discover locally represented rewards for movie fans and popcorn fans alike.</p><a class="button" href="/sign-up">Join AMC Stubs</a></div></section>
<section class="home-promotion reverse"><div class="promotion-image" style="background-image:url('/local-assets/promo-tony.jpg')"></div><div class="promotion-copy"><p class="eyebrow red">Now showing</p><h2>Where A Legends Story Began</h2><p>Experience unforgettable stories and discover what is playing at AMC.</p><a class="button" href="/movies">Browse movies</a></div></section>
<section class="home-promotion"><div class="promotion-image" style="background-image:url('/local-assets/promo-cherry-coke.jpg')"></div><div class="promotion-copy"><p class="eyebrow red">A new classic</p><h2>Float Away with a New Classic</h2><p>Enjoy a bright local taste of the concession experience before the trailers begin.</p><a class="button" href="/help">Learn more</a></div></section>
<section class="home-promotion reverse"><div class="promotion-image" style="background-image:url('/local-assets/promo-super-troopers.jpg')"></div><div class="promotion-copy"><p class="eyebrow red">Movie night energy</p><h2>The Official Fuel for Shenanigans</h2><p>Bring the crew together, choose a local showtime and settle in for the feature.</p><a class="button" href="/showtimes">Get tickets</a></div></section>
<section id="offers" class="offers-cta"><div class="wrap"><h2>Make Movies More Rewarding</h2><a class="button white" href="/sign-up">Join AMC Stubs</a></div></section><div class="pre-footer-space" aria-hidden="true"></div>"""
    return with_session(HTMLResponse(layout("Movies at AMC", body, state)), token, request)


FEATURE_PAGES = {
    "/food-and-drink": ("Food & Drinks", "Make movie night delicious", [
        ("AMC Perfectly Popcorn", "Freshly popped classics and shareable sizes for every movie night.", "/movie-theatres"),
        ("Dine-In at AMC", "Choose a participating theatre and explore local dine-in availability.", "/movie-theatres"),
        ("Order ahead", "Pick a theatre and showtime before building a local concession plan.", "/showtimes"),
    ]),
    "/group-events": ("Group Events", "Bring your group to the big screen", [
        ("Private theatre rental", "Plan a synthetic private screening for friends, teams or community groups.", "/help"),
        ("School and community", "Review accessible planning information before contacting a theatre.", "/help"),
        ("Corporate events", "Start with a theatre and date, then continue through local support.", "/movie-theatres"),
    ]),
    "/merchandise": ("Merchandise", "Collect a piece of movie night", [
        ("Featured collectibles", "Browse locally represented concession vessels and limited movie items.", "/offers"),
        ("Gift-ready ideas", "Pair an AMC gift card with an upcoming movie.", "/gift-cards"),
    ]),
    "/gift-cards": ("Gift Cards", "Give the gift of movies", [
        ("Digital gift card", "Choose a local demonstration amount without sending mail or charging a card.", "/sign-up"),
        ("Use a gift card", "Sign in to the synthetic AMC account to review local wallet options.", "/login"),
    ]),
    "/offers": ("Offers", "More ways to enjoy AMC", [
        ("AMC Stubs", "Join the local synthetic membership experience and save favorites.", "/sign-up"),
        ("Tuesday savings", "Find a participating local showtime in the clone.", "/showtimes"),
        ("Featured movie offers", "Browse current titles and their available local sessions.", "/movies"),
    ]),
    "/on-demand": ("AMC Theatres On Demand", "Movies wherever your screen is", [
        ("Browse movies", "Explore the clone collection and open every local detail page.", "/movies"),
        ("Saved movies", "Sign in to revisit favorites from the synthetic account.", "/login"),
    ]),
}


@app.get("/food-and-drink", response_class=HTMLResponse)
@app.get("/group-events", response_class=HTMLResponse)
@app.get("/merchandise", response_class=HTMLResponse)
@app.get("/gift-cards", response_class=HTMLResponse)
@app.get("/offers", response_class=HTMLResponse)
@app.get("/on-demand", response_class=HTMLResponse)
def feature_page(request: Request) -> HTMLResponse:
    token, state = session(request)
    title, heading, items = FEATURE_PAGES[request.url.path]
    if request.url.path == "/offers":
        cards = "".join(
            f'''<article class="offer-card"><img src="/local-assets/{esc(image)}" alt=""><div><p class="eyebrow red">{esc(category)}</p><h2>{esc(name)}</h2><p>{esc(copy)}</p><a class="button compact" href="{esc(href)}">{esc(action)}</a></div></article>'''
            for category, name, copy, image, action, href in OFFER_ITEMS
        )
        body = f'''<section class="page-head dark-head"><div class="wrap"><p class="eyebrow light">Offers &amp; Promotions</p><h1>{esc(heading)}</h1><p>Explore ticket, membership, food and discount offers available in this local experience.</p></div></section><nav class="offer-nav wrap" aria-label="Offer categories"><a href="#special-offers">Special Offers &amp; Events</a><a href="#stubs">AMC Stubs Exclusives</a><a href="#food-offers">Food &amp; Drink</a><a href="#discounts">Discounts</a></nav><section id="special-offers" class="section wrap"><div class="offer-page-grid">{cards}</div></section>'''
        return with_session(HTMLResponse(layout(title, body, state)), token, request)
    if request.url.path == "/food-and-drink":
        cards = "".join(
            f'''<article class="offer-card"><img src="/local-assets/{esc(image)}" alt=""><div><p class="eyebrow red">Food &amp; Drinks</p><h2>{esc(name)}</h2><p>{esc(copy)}</p><a class="button compact" href="/food-and-drink/{esc(slug)}">Explore</a></div></article>'''
            for slug, name, copy, image in FOOD_ITEMS
        )
        body = f'''<section class="feature-hero food-hero"><div class="wrap"><p class="eyebrow light">Food &amp; Drinks at AMC</p><h1>{esc(heading)}</h1><p>Explore classic concessions, dine-in menus, collectibles and special offers.</p><a class="button" href="#food-menu">Explore Menus</a></div></section><section id="food-menu" class="section wrap"><div class="offer-page-grid">{cards}</div></section>'''
        return with_session(HTMLResponse(layout(title, body, state)), token, request)
    cards = "".join(
        f'<article class="theatre-card"><div><p class="eyebrow red">AMC</p><h2>{esc(name)}</h2><p>{esc(copy)}</p></div><a class="button compact" href="{esc(href)}">Explore</a></article>'
        for name, copy, href in items
    )
    body = f'<section class="page-head dark-head"><div class="wrap"><p class="eyebrow light">{esc(title)}</p><h1>{esc(heading)}</h1><p>All actions remain inside the deterministic local AMC clone.</p></div></section><section class="section wrap"><div class="theatre-list">{cards}</div></section>'
    return with_session(HTMLResponse(layout(title, body, state)), token, request)


@app.get("/food-and-drink/{slug}", response_class=HTMLResponse)
def food_detail(slug: str, request: Request) -> HTMLResponse:
    token, state = session(request)
    item = next((entry for entry in FOOD_ITEMS if entry[0] == slug), None)
    if item is None:
        return with_session(HTMLResponse(layout("Food item not found", '<section class="empty"><h1>Food item not found</h1><a href="/food-and-drink">Explore food and drinks</a></section>', state), status_code=404), token, request)
    _slug, name, copy, image = item
    body = f'''<section class="feature-detail"><div class="wrap feature-detail-grid"><img src="/local-assets/{esc(image)}" alt=""><div><p class="eyebrow red">Food &amp; Drinks at AMC</p><h1>{esc(name)}</h1><p class="lede dark">{esc(copy)}</p><h2>Made for movie night</h2><p>Availability varies by theatre. Choose a local theatre to continue without leaving the offline clone.</p><a class="button" href="/movie-theatres">Find a Theatre</a><a class="text-link" href="/food-and-drink">Back to Food &amp; Drinks</a></div></div></section>'''
    return with_session(HTMLResponse(layout(name, body, state, active="food")), token, request)


@app.get("/movies", response_class=HTMLResponse)
def movies(request: Request, q: str = "", genre: str = "All", sort: str = "Featured") -> HTMLResponse:
    token, state = session(request)
    movie_list = request.query_params.get("movie-list", "")
    if movie_list == "coming-soon":
        result = [item for item in MOVIES if item["tag"] == "Coming Soon"]
    else:
        result = list(MOVIES[:23])
    if q:
        result = [m for m in result if q.lower() in (m["title"] + " " + m["genre"]).lower()]
    if genre != "All":
        result = [m for m in result if genre.lower() in m["genre"].lower()]
    if sort == "A-Z":
        result.sort(key=lambda m: m["title"])
    elif sort == "Audience Score":
        result.sort(key=lambda m: m["score"], reverse=True)
    elif not q and genre == "All":
        featured = [
            "insidious-out-of-the-further",
            "spider-man-brand-new-day",
            "the-odyssey",
            "paw-patrol-dino-movie",
            "the-end-of-oak-street",
        ]
        positions = {slug: index for index, slug in enumerate(featured)}
        result.sort(key=lambda item: positions.get(item["slug"], len(featured) + MOVIES.index(item)))
    favorites = favorite_slugs(token)
    cards = "".join(movie_listing_card(item, item["slug"] in favorites) for item in result)
    body = f"""<section class="movies-page"><div class="wrap"><h1>Movies at AMC</h1><div class="movies-page-toolbar"><button class="featured-select" type="button" aria-expanded="false" aria-controls="featured-menu">Featured Movies<span></span></button><div id="featured-menu" class="featured-menu" hidden><a href="/movies?sort=Featured">Featured</a><a href="/movies?sort=A-Z">A-Z</a><a href="/movies?sort=Audience%20Score">Audience Score</a></div><nav aria-label="Movie categories"><a class="{'on' if movie_list != 'coming-soon' else ''}" href="/movies">Now Playing</a><a href="/movies?genre=Events">Events</a><a class="{'on' if movie_list == 'coming-soon' else ''}" href="/movies?movie-list=coming-soon">Coming Soon</a></nav></div><form class="movies-page-filter"><input type="hidden" name="movie-list" value="{esc(movie_list)}"><span>FILTER BY</span><label><span class="filter-sliders">↕</span><select name="genre" aria-label="Premium Offerings"><option value="All">Premium Offerings</option><option>IMAX</option><option>Dolby Cinema</option></select></label><input class="listing-search" name="q" value="{esc(q)}" aria-label="Search movies" placeholder="Search movies"><select class="listing-sort" name="sort" aria-label="Sort movies">{''.join(f'<option {"selected" if s == sort else ""}>{s}</option>' for s in ["Featured","A-Z","Audience Score"])}</select><button>Apply</button></form><p class="sr-only">{len(result)} movies</p><div class="movies-page-grid">{cards or '<div class="empty movies-empty"><h2>No movies found</h2><p>Try a broader search or reset the filters.</p><a href="/movies">Reset filters</a></div>'}</div></div></section>"""
    return with_session(HTMLResponse(layout("Movies", body, state, active="movies")), token, request)


@app.get("/movies/{slug}", response_class=HTMLResponse)
def movie_detail(slug: str, request: Request) -> HTMLResponse:
    token, state = session(request)
    item = movie(slug)
    if item is None:
        return with_session(HTMLResponse(layout("Movie not found", '<section class="empty"><h1>Movie not found</h1><a href="/movies">Browse movies</a></section>', state), status_code=404), token, request)
    saved = slug in favorite_slugs(token)
    poster = poster_image(item)
    gallery = "".join(
        f'<img src="/local-assets/{esc(image)}" alt="Scene from {esc(item["title"])}">'
        for image in [poster, "showtime-video.jpg", "movies-exact.avif"]
    )
    body = f"""<section class="detail-hero movie-detail-hero" style="background-image:linear-gradient(90deg,#000 0%,#000d 42%,#0002 100%),url('/local-assets/{esc(poster)}')"><div class="wrap detail-grid"><img class="detail-poster" src="/local-assets/{esc(poster)}" alt="{esc(item['title'])} poster"><div><p class="eyebrow light">{esc(item['tag'])}</p><h1>{esc(item['title'])}</h1><p class="metadata">{esc(item['rating'])} · {esc(item['runtime'])} · {esc(item['genre'])}</p><p class="lede">{esc(item['desc'])}</p><div class="score"><strong>{item['score']}%</strong><span>AMC audience score</span></div><div class="detail-actions"><a class="button" href="/showtimes?movie={esc(slug)}">Choose a showtime</a><button class="button white heart-detail {'saved' if saved else ''}" data-favorite="{esc(slug)}" data-title="{esc(item['title'])}" aria-pressed="{'true' if saved else 'false'}" aria-label="{'Remove from saved movies' if saved else 'Save to My AMC'}">♥ {'Saved to My AMC' if saved else 'Save to My AMC'}</button></div></div></div></section><section class="section wrap movie-information"><div><p class="eyebrow red">Movie details</p><h2>About the movie</h2><p class="lede dark">{esc(item['desc'])} Experience the story on the big screen with available reserved seating and premium-format options.</p></div><dl><div><dt>Genre</dt><dd>{esc(item['genre'])}</dd></div><div><dt>Rating</dt><dd>{esc(item['rating'])}</dd></div><div><dt>Runtime</dt><dd>{esc(item['runtime'])}</dd></div><div><dt>Language</dt><dd>English</dd></div></dl><div class="movie-gallery"><h2>Scenes from the movie</h2><div>{gallery}</div></div></section>"""
    return with_session(HTMLResponse(layout(item["title"], body, state, active="movies")), token, request)


@app.get("/movie-theatres", response_class=HTMLResponse)
def theatres(request: Request, q: str = "") -> HTMLResponse:
    token, state = session(request)
    result = [t for t in THEATRES if not q or q.lower() in (t["name"] + " " + t["city"] + " " + t["state"] + " " + t["address"]).lower()]
    theatre_cards = "".join(f"""<article class="theatre-card"><div><p class="eyebrow red">{t['miles']} miles away</p><h2><a href="/movie-theatres/{t['state'].lower()}/{t['slug']}">{esc(t['name'])}</a></h2><p>{esc(t['address'])}</p><div class="chips">{''.join(f'<span>{esc(f)}</span>' for f in t['features'])}</div></div><a class="button compact" href="/movie-theatres/{t['state'].lower()}/{t['slug']}">View Showtimes</a></article>""" for t in result)
    if q:
        body = f"""<section class="page-head dark-head"><div class="wrap"><p class="eyebrow light">Find your AMC</p><h1>Movie Theatres Near You</h1><form class="theatre-search"><input name="q" value="{esc(q)}" placeholder="City, state, ZIP or theatre name"><button class="button white">Search</button></form></div></section><section class="section wrap"><p class="result-count">{len(result)} theatres found</p><div class="theatre-list">{theatre_cards or '<div class="empty"><h2>No theatres found</h2><p>Try a city such as New York, Los Angeles or Chicago.</p></div>'}</div></section>"""
    else:
        market_links = "".join(
            f'<div><a href="{esc(href)}">{esc(label)}</a></div>' for label, href in DIRECTORY_MARKETS
        )
        state_links = "".join(
            f'<div><a href="/movie-theatres?q={quote(label)}">{esc(label)}</a></div>'
            for label in [
                "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
                "Connecticut", "Delaware", "Florida", "Georgia", "Idaho", "Illinois",
                "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maryland",
                "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
                "Montana", "Nebraska", "Nevada", "New Jersey", "New Mexico", "New York",
                "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
                "Pennsylvania", "South Carolina", "South Dakota", "Tennessee", "Texas",
                "Utah", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
            ]
        )
        body = f"""<section class="theatre-directory"><div class="wrap"><h1>Find a Theatre</h1><form class="directory-search"><label class="sr-only" for="theatre-q">Theatre Search</label><input id="theatre-q" name="q" placeholder="Search by City, Zip or Theatre"><button class="directory-search-button" aria-label="Search"><img src="/local-icons/search-muted.svg" alt=""></button></form><button class="use-location" type="button" data-current-location><span>◎</span>Use Current Location</button><section class="directory-index"><div class="directory-index-heading"><h2>All Theatres</h2><div role="tablist" aria-label="Theatre directory"><button class="on" type="button" role="tab" aria-selected="true" data-directory-tab="markets">Markets</button><button type="button" role="tab" aria-selected="false" data-directory-tab="states">States</button></div></div><div class="directory-links" data-directory-panel="markets">{market_links}</div><div class="directory-links state-links" data-directory-panel="states" hidden>{state_links}</div></section></div></section>"""
    return with_session(HTMLResponse(layout("Movie Theatres", body, state, active="theatres")), token, request)


@app.get("/movie-theatres/{market}", response_class=HTMLResponse)
def theatre_market(market: str, request: Request) -> RedirectResponse:
    label = next((name for name, href in DIRECTORY_MARKETS if href.rsplit("/", 1)[-1] == market), market.replace("-", " ").title())
    token, _state = session(request)
    return with_session(RedirectResponse(url=f"/movie-theatres?q={quote(label)}", status_code=303), token, request)


@app.get("/movie-theatres/{region}/{slug}", response_class=HTMLResponse)
def theatre_detail(region: str, slug: str, request: Request) -> HTMLResponse:
    del region
    token, state = session(request)
    item = theatre(slug)
    if item is None:
        return with_session(HTMLResponse(layout("Theatre not found", '<section class="empty"><h1>Theatre not found</h1><a href="/movie-theatres">Find a theatre</a></section>', state), status_code=404), token, request)
    theatre_features = ["IMAX with Laser at AMC", "Dolby Cinema at AMC", "PRIME at AMC", "Discount Tuesdays and Wednesdays", "Discount Matinees", "Open Caption (On-Screen Subtitles)", "XL at AMC", "AMC Club Rockers", "Laser at AMC", "AMC Artisan Films"]
    preview_movies = [
        ("the-end-of-oak-street", "Irumudi", "theatre-poster-irumudi.avif"),
        ("the-end-of-oak-street", "It Ends", "theatre-poster-it-ends.avif"),
        ("the-end-of-oak-street", "The End of Oak Street", "theatre-poster-oak.avif"),
        ("the-odyssey", "The Odyssey", "theatre-poster-odyssey.avif"),
        ("paw-patrol-dino-movie", "PAW Patrol: The Dino Movie", "theatre-poster-paw.avif"),
    ]
    previews = "".join(
        f'''<article class="theatre-preview"><a href="/movies/{esc(movie_slug)}"><img src="/local-assets/{esc(image)}" alt="{esc(title)}"></a><h3>{esc(title)}</h3><div>{''.join(f'<a class="showtime" href="/checkout/{esc(movie_slug)}?theatre={esc(slug)}&amp;time={quote(t)}">{esc(t)}</a>' for t in SHOWTIMES[:3])}</div></article>'''
        for movie_slug, title, image in preview_movies
    )
    feature_list = "".join(f"<li>{esc(feature)}</li>" for feature in theatre_features)
    favorite_icon = '<svg fill="currentColor" viewBox="0 0 45 45" aria-hidden="true"><path d="M22.5 0a22.5 22.5 0 1 0 0 45 22.5 22.5 0 0 0 0-45m0 43.172a20.672 20.672 0 1 1 0-41.344 20.672 20.672 0 0 1 0 41.344"></path><path d="M17.466 30.206c-.293 0-.644-.166-.83-.39-.186-.226-.284-.648-.23-.937l.843-5.01-3.662-3.546a1.25 1.25 0 0 1-.306-1.15 1.25 1.25 0 0 1 .92-.748l5.042-.746 2.245-4.581a1.26 1.26 0 0 1 .995-.644 1.27 1.27 0 0 1 .996.638l2.272 4.568 5.046.72a1.26 1.26 0 0 1 .92.74 1.27 1.27 0 0 1-.299 1.15l-3.639 3.569.878 5.023a1.3 1.3 0 0 1-.24.93c-.292.344-.978.45-1.372.245l-4.523-2.356-4.502 2.385a1.4 1.4 0 0 1-.554.14m-1.69-10.17 2.778 2.695a1.61 1.61 0 0 1 .456 1.386l-.642 3.822 3.42-1.814a2.3 2.3 0 0 1 .737-.174c.26 0 .51.059.723.171l3.431 1.795-.663-3.82a1.61 1.61 0 0 1 .447-1.395l2.759-2.705-3.828-.546a1.62 1.62 0 0 1-1.187-.858l-1.718-3.462-1.702 3.474a1.64 1.64 0 0 1-1.167.863z"></path></svg>'
    nearby_icon = '<svg fill="currentColor" viewBox="0 0 45 45" aria-hidden="true"><path d="M22.5 0a22.5 22.5 0 1 0 0 45 22.5 22.5 0 0 0 0-45m0 43.172a20.672 20.672 0 1 1 0-41.344 20.672 20.672 0 0 1 0 41.344"></path><path d="M22.5 12.572c-3.65 0-6.62 2.933-6.62 6.545 0 7.692 6.055 12.982 6.313 13.201a.48.48 0 0 0 .616 0c.26-.219 6.312-5.51 6.312-13.201 0-3.612-2.973-6.545-6.621-6.545m0 17.778c-1.091-1.05-5.057-5.263-5.057-10.87 0-2.751 2.27-4.993 5.057-4.993 2.79 0 5.06 2.242 5.06 4.992 0 5.597-3.966 9.822-5.06 10.87m0-14.453a3.524 3.524 0 1 0 .003 7.046 3.524 3.524 0 0 0-.003-7.046m0 5.479a1.955 1.955 0 1 1 .006-3.91 1.955 1.955 0 0 1-.006 3.91"></path></svg>'
    body = f"""<section class="theatre-source-hero"><div class="wrap"><ul class="theatre-source-features">{feature_list}</ul><h1>{esc(item['name'])}</h1><p class="theatre-source-address">{esc(item['address'])}</p><div class="theatre-source-actions"><a class="theatre-primary" href="/showtimes?theatre={esc(slug)}">Get Tickets</a><a class="theatre-primary food" href="/help?q=food">Order Food &amp; Drinks</a><button type="button" data-favorite-theatre data-theatre="{esc(slug)}" data-theatre-name="{esc(item['name'])}" data-authenticated="{str(bool(state.get('authenticated'))).lower()}" aria-pressed="false">{favorite_icon}<span>Add Favorite</span></button><a class="nearby" href="/movie-theatres">{nearby_icon}<span>Nearby Theatres</span></a></div></div></section><section class="theatre-source-movies"><div class="wrap"><div class="theatre-source-movies-head"><h2>Movies at this Theatre</h2><label>See it <select aria-label="Movie date"><option>Today, Aug 23</option><option>Tomorrow, Aug 24</option></select></label></div><div class="theatre-preview-rail">{previews}</div></div></section>"""
    return with_session(HTMLResponse(layout(item["name"], body, state, active="theatres")), token, request)


@app.get("/showtimes", response_class=HTMLResponse)
def showtimes(request: Request, movie: str = "", location: str = "New York", date: str = "") -> HTMLResponse:
    token, state = session(request)
    del state
    requested_theatre = request.query_params.get("theatre", "") or location
    selected_venue = globals()["theatre"](requested_theatre)
    if selected_venue is None and request.query_params.get("theatre"):
        needle = requested_theatre.lower()
        selected_venue = next(
            (item for item in THEATRES if needle in (item["name"] + " " + item["city"] + " " + item["state"] + " " + item["address"]).lower()),
            None,
        )
    selected_theatre = selected_venue["slug"] if selected_venue else ""
    theatre_query = f"&amp;theatre={quote(selected_theatre)}" if selected_theatre else ""
    showtime_order = [
        "insidious-out-of-the-further", "spider-man-brand-new-day",
        "the-odyssey", "paw-patrol-dino-movie",
    ]
    selected_film = globals()["movie"](movie) if movie else None
    films = [selected_film] if selected_film else [globals()["movie"](slug) for slug in showtime_order]
    films = [item for item in films if item is not None]
    premium = request.query_params.get("format") == "premium"
    available_times = SHOWTIMES[1:7] if date == "tomorrow" else SHOWTIMES[:6]
    rows = []
    for film in films:
        runtime, rating, _release = LISTING_META.get(
            film["slug"], (film["runtime"], film["rating"].replace("-", ""), "")
        )
        image = {
            "insidious-out-of-the-further": "showtime-insidious.jpg",
            "spider-man-brand-new-day": "showtime-spiderman.jpg",
            "the-odyssey": "showtime-odyssey.png",
            "paw-patrol-dino-movie": "showtime-pawpatrol.jpg",
        }.get(film["slug"], poster_image(film))
        format_label = "IMAX and Dolby Cinema" if premium else "Reserved Seating · Laser at AMC"
        time_links = "".join(
            f'<a class="showtime" href="/checkout/{esc(film["slug"])}?theatre={esc(selected_theatre)}&amp;time={quote(value)}">{esc(value)}</a>'
            for value in available_times
        )
        rows.append(
            f"""<article class="showtimes-movie has-times"><img src="/local-assets/{esc(image)}" alt=""><div class="showtimes-copy"><h2><a href="/movies/{esc(film['slug'])}">{esc(film['title'])}</a></h2><p>{esc(runtime)} <span class="showtime-info">?</span> | {esc(rating)}</p><p class="showtime-format">{esc(format_label)}</p></div><div class="showtimes-options">{time_links}</div></article>"""
        )
    today_label = "Tomorrow" if date == "tomorrow" else "Today"
    back_icon = '<svg fill="currentColor" viewBox="0 0 45 45" aria-hidden="true"><path d="M14.974 22.5 34.321 3.153A2.09 2.09 0 0 0 31.46.291l-20.892 20.75a2.09 2.09 0 0 0 0 2.861L31.373 44.71a2.09 2.09 0 0 0 2.862-2.862z"></path></svg>'
    close_icon = '<svg fill="currentColor" stroke="currentColor" viewBox="0 0 45 45" aria-hidden="true"><path stroke-width="4.0358" d="M40.341 4.769a1.11 1.11 0 0 1-.022 1.587L24.071 22.604 40.32 38.85a1.112 1.112 0 0 1-1.566 1.566L22.506 24.169 6.236 40.417a1.112 1.112 0 0 1-1.565-1.566l16.27-16.247L4.67 6.356a1.13 1.13 0 0 1-.303-.767A1.13 1.13 0 0 1 5.49 4.465c.285 0 .56.11.768.304l16.248 16.269 16.268-16.27a1.117 1.117 0 0 1 1.566 0Z"></path></svg>'
    theatre_icon = '<svg fill="none" viewBox="0 0 24 24" aria-hidden="true"><path fill="#fff" fill-rule="evenodd" d="M12 10.35a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3m0 1.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6" clip-rule="evenodd"></path><path fill="#fff" fill-rule="evenodd" d="M12 2.35a6.5 6.5 0 0 0-6.295 8.126c.388 1.509 1.733 4.358 3.283 6.884.765 1.247 1.537 2.344 2.21 3.11.328.374.598.63.802.784.204-.154.474-.41.802-.783.673-.767 1.445-1.864 2.21-3.111 1.55-2.526 2.895-5.375 3.283-6.884A6.5 6.5 0 0 0 12 2.35m7.748 8.5a8 8 0 1 0-15.496 0C5.14 14.3 10 22.85 12 22.85s6.86-8.55 7.748-12" clip-rule="evenodd"></path></svg>'
    date_icon = '<svg fill="none" viewBox="0 0 24 24" aria-hidden="true"><path fill="#fff" d="M6.5 11a1.5 1.5 0 0 0 0 3h1a1.5 1.5 0 0 0 0-3z"></path><path fill="#fff" fill-rule="evenodd" d="M7 0a1 1 0 0 1 1 1v1h8V1a1 1 0 1 1 2 0v1h2a3 3 0 0 1 3 3v14a3 3 0 0 1-3 3H4a3 3 0 0 1-3-3V5a3 3 0 0 1 3-3h2V1a1 1 0 0 1 1-1m9 3.5V4a1 1 0 1 0 2 0v-.5h2A1.5 1.5 0 0 1 21.5 5v2.25h-19V5A1.5 1.5 0 0 1 4 3.5h2V4a1 1 0 0 0 2 0v-.5zM2.5 8.75h19V19a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 19z" clip-rule="evenodd"></path></svg>'
    movie_icon = '<svg fill="none" viewBox="0 0 24 24" aria-hidden="true"><path fill="#fff" fill-rule="evenodd" d="M1 5a2 2 0 0 1 2-2h18a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2zm6 10a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2zm-4 1a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1zm15 1a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1zM3 10a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1zm15 1a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1zM3 4a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1zm15 1a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1zM9 4a2 2 0 0 0-2 2v3a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z" clip-rule="evenodd"></path></svg>'
    premium_icon = '<svg fill="none" viewBox="0 0 24 24" aria-hidden="true"><path fill="#fff" fill-rule="evenodd" d="M2.75 8q0 .134.027.26a3 3 0 0 0 0 5.48q-.027.125-.027.26v7a1.25 1.25 0 1 0 2.5 0v-7q0-.134-.027-.26a3 3 0 0 0 0-5.48q.027-.126.027-.26V3a1.25 1.25 0 1 0-2.5 0zM4 12.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3M21.223 9.74a3 3 0 0 0 0-5.48q.027-.125.027-.26V3a1.25 1.25 0 1 0-2.5 0v1q0 .135.027.26a3 3 0 0 0 0 5.48q-.027.125-.027.26v11a1.25 1.25 0 1 0 2.5 0V10q0-.134-.027-.26M21.5 7a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0M13.223 19.74a3 3 0 0 0 0-5.48q.027-.125.027-.26V3a1.25 1.25 0 1 0-2.5 0v11q0 .134.027.26a3 3 0 0 0 0 5.48q-.027.125-.027.26v1a1.25 1.25 0 1 0 2.5 0v-1q0-.134-.027-.26M12 18.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3" clip-rule="evenodd"></path></svg>'
    down_icon = '<svg fill="currentColor" viewBox="0 0 45 45" aria-hidden="true"><path d="M22.464 29.594 3.067 10.48c-.856-.57-2.283-.285-2.853.856-.285.57-.285 1.141 0 1.997l20.824 20.824c.856.856 1.997.856 2.853 0L44.715 13.62c.57-.856.285-2.282-.856-2.852-.57-.286-1.426-.286-1.997 0z"></path></svg>'
    movie_query = f"&amp;movie={quote(movie)}" if selected_film else ""
    date_query = f"&amp;date={quote(date)}" if date else ""
    format_query = "&amp;format=premium" if premium else ""
    if not selected_theatre:
        quick_theatres = "".join(
            f'<a class="picker-theatre" href="/showtimes?theatre={esc(item["slug"])}{movie_query}{date_query}{format_query}"><span><strong>{esc(item["name"])}</strong><small>{esc(item["city"])} · {item["miles"]} miles</small></span><b>›</b></a>'
            for item in [THEATRES[0], THEATRES[4], THEATRES[5]]
        )
        hidden_movie = f'<input type="hidden" name="movie" value="{esc(movie)}">' if selected_film else ""
        picker = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Find a Theatre | AMC Theatres</title><link rel="stylesheet" href="/assets/amc.css"></head><body class="showtimes-shell theatre-picker-shell"><main class="showtimes-page"><header class="showtimes-top"><h1>Showtimes</h1><a href="/" aria-label="Close">{close_icon}</a></header><aside class="picker-backdrop-copy"><p>In order to display showtimes, please select a theatre.</p><a href="/showtimes?theatre=amc-empire-25{movie_query}">Select a Theatre</a></aside><section class="theatre-picker" role="dialog" aria-modal="true" aria-labelledby="theatre-picker-title"><header><h1 id="theatre-picker-title">Find a Theatre</h1><a href="/" aria-label="Close">{close_icon}</a></header><div class="theatre-picker-body"><p>Select a theatre to view showtimes.</p><form action="/showtimes">{hidden_movie}<label class="sr-only" for="showtimes-theatre">Search by City, Zip or Theatre</label><div class="picker-input-box"><input id="showtimes-theatre" name="theatre" placeholder="Search by City, Zip or Theatre" required><button type="submit" aria-label="Search theatres"><img src="/local-icons/search.svg" alt=""></button></div></form><a class="picker-location" href="/showtimes?theatre=amc-empire-25{movie_query}">Use Current Location</a><div class="picker-divider">Popular theatres</div>{quick_theatres}</div></section></main></body></html>"""
        return with_session(HTMLResponse(picker), token, request)
    featured = films[0]
    next_date = "" if date == "tomorrow" else "tomorrow"
    next_date_query = f"&amp;date={next_date}" if next_date else ""
    movie_filter_label = featured["title"] if selected_film else "All Movies"
    premium_target = "" if premium else "premium"
    premium_target_query = f"&amp;format={premium_target}" if premium_target else ""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Showtimes | AMC Theatres</title><link rel="stylesheet" href="/assets/amc.css"></head><body class="showtimes-shell"><main class="showtimes-page"><header class="showtimes-top"><a href="/" aria-label="Go back">{back_icon}</a><h1>Showtimes</h1><a href="/" aria-label="Close">{close_icon}</a></header><nav class="showtimes-filters" aria-label="Showtime filters"><a href="/showtimes?movie={quote(movie) if selected_film else ''}{date_query}{format_query}"><span>{theatre_icon}</span><strong>{esc(selected_venue['name'])}</strong><b>{down_icon}</b></a><a href="/showtimes?theatre={quote(selected_theatre)}{movie_query}{next_date_query}{format_query}"><span>{date_icon}</span><strong>{today_label}</strong><b>{down_icon}</b></a><a href="/showtimes?theatre={quote(selected_theatre)}{date_query}{format_query}"><span>{movie_icon}</span><strong>{esc(movie_filter_label)}</strong><b>{down_icon}</b></a><a href="/showtimes?theatre={quote(selected_theatre)}{movie_query}{date_query}{premium_target_query}"><span>{premium_icon}</span><strong>Premium Offerings</strong><b>{down_icon}</b></a></nav><div class="showtimes-content"><section class="showtimes-list"><p class="showtimes-note"><span>{movie_icon}</span> Movies start 25-30 minutes after showtime.</p>{''.join(rows)}</section><aside class="showtimes-feature"><img src="/local-assets/{esc(poster_image(featured))}" alt=""><h2>{esc(featured['title'])}</h2><p>{esc(featured['runtime'])} <span class="showtime-info">?</span> | {esc(featured['rating'])}</p><a href="/movies/{esc(featured['slug'])}"><span>{movie_icon}</span> Movie Info <b>›</b></a></aside></div></main><script src="/assets/amc.js"></script></body></html>"""
    return with_session(HTMLResponse(page), token, request)


@app.get("/checkout/{slug}", response_class=HTMLResponse)
def checkout(slug: str, request: Request, theatre: str = "amc-empire-25", time: str = "7:00 PM") -> HTMLResponse:
    token, state = session(request)
    film, venue = movie(slug), globals()["theatre"](theatre)
    if film is None or venue is None:
        return with_session(HTMLResponse(layout("Showtime not found", '<section class="empty"><h1>Showtime not found</h1><a href="/showtimes">Browse showtimes</a></section>', state), status_code=404), token, request)
    seats = "".join(f'<button type="button" class="seat" data-seat="{row}{number}" aria-label="Seat {row}{number}">{row}{number}</button>' for row in "ABCDE" for number in range(1, 9))
    body = f"""<section class="checkout-head"><div class="wrap"><a href="/showtimes">← Back to showtimes</a><h1>{esc(film['title'])}</h1><p>{esc(venue['name'])} · Today at {esc(time)}</p></div></section><section class="checkout-grid wrap"><div><h2>Choose your seats</h2><p>Select up to 8 seats. Reserved seats are held only for this local session.</p><div class="screen">SCREEN</div><div class="seat-map">{seats}</div><div class="seat-legend"><span>□ Available</span><span>■ Selected</span></div></div><aside class="order-card"><h2>Your order</h2><label>Ticket type<select id="ticket-type"><option>Adult</option><option>Child</option><option>Senior</option></select></label><label>Format<select id="format-name"><option>Standard</option><option>IMAX</option><option>Dolby Cinema</option></select></label><label>Attendee name<input id="attendee-name" maxlength="80" value="Local Guest" required></label><dl aria-label="Booking review"><div><dt>Movie</dt><dd>{esc(film['title'])}</dd></div><div><dt>Theatre</dt><dd>{esc(venue['name'])}</dd></div><div><dt>Seats</dt><dd id="selected-seats">None</dd></div><div><dt>Tickets</dt><dd id="ticket-count">0</dd></div><div><dt>Ticket type</dt><dd id="review-ticket-type">Adult</dd></div><div><dt>Format</dt><dd id="review-format">Standard</dd></div><div><dt>Attendee</dt><dd id="review-attendee">Local Guest</dd></div><div class="total"><dt>Total</dt><dd id="order-total">$0.00</dd></div></dl><label>Payment simulation<select id="scenario"><option value="sandbox-approved">Simulated approval</option><option value="sandbox-declined">Simulated decline</option><option value="sandbox-retry">Simulated retry</option></select></label><button id="place-order" class="button full" data-movie="{esc(slug)}" data-theatre="{esc(theatre)}" data-time="{esc(time)}" disabled>Complete Sandbox Order</button><p class="fine-print">Review the summary above before completing. Edit any seat, ticket, format, or attendee field and the review updates immediately. No card details or real payment are collected.</p></aside></section>"""
    return with_session(HTMLResponse(layout("Choose Seats", body, state)), token, request)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/account") -> HTMLResponse:
    token, state = session(request)
    body = f"""<section class="auth-shell"><div class="auth-card"><p class="eyebrow red">Welcome back</p><h1>Sign in to My AMC</h1><p>Use a synthetic local account. Never enter credentials from the real AMC site.</p><form id="login-form"><input type="hidden" name="next" value="{esc(next)}"><label>Email<input name="email" type="email" autocomplete="email" required></label><label>Password<input name="password" type="password" autocomplete="current-password" required></label><label class="captcha-control"><input name="captcha" type="checkbox" required><span><strong>I'm not a robot</strong><small>Local verification · no external CAPTCHA service</small></span><b aria-hidden="true">✓</b></label><button class="button full">Sign In</button><p class="form-message" role="alert"></p></form><p><a href="/password-reset">Forgot password?</a></p><p class="auth-switch">New to AMC? <a href="/sign-up">Create an account</a></p></div></section>"""
    return with_session(HTMLResponse(layout("Sign In", body, state)), token, request)


@app.get("/sign-up", response_class=HTMLResponse)
def signup_page(request: Request, plan: str = "") -> HTMLResponse:
    token, state = session(request)
    if plan:
        selected_plan = plan if plan in {"insider", "premiere", "alist", "register"} else "insider"
        body = f"""<section class="auth-shell"><div class="auth-card"><p class="eyebrow red">AMC Stubs {esc(selected_plan.title())}</p><h1>Join for free</h1><p>Create a local demo account to save movies and orders.</p><form id="signup-form"><input type="hidden" name="plan" value="{esc(selected_plan)}"><label>Name<input name="name" required></label><label>Email<input name="email" type="email" required></label><label>Password<input name="password" type="password" minlength="8" required></label><button class="button full">Create Account</button><p class="form-message" role="alert"></p></form><p class="auth-switch">Already a member? <a href="/login">Sign in</a></p></div></section>"""
        return with_session(HTMLResponse(layout("Join AMC Stubs", body, state)), token, request)
    close_icon = '<svg fill="currentColor" stroke="currentColor" viewBox="0 0 45 45" aria-hidden="true"><path stroke-width="4.0358" d="M40.341 4.769a1.11 1.11 0 0 1-.022 1.587L24.071 22.604 40.32 38.85a1.112 1.112 0 0 1-1.566 1.566L22.506 24.169 6.236 40.417a1.112 1.112 0 0 1-1.565-1.566l16.27-16.247L4.67 6.356a1.13 1.13 0 0 1-.303-.767A1.13 1.13 0 0 1 5.49 4.465c.285 0 .56.11.768.304l16.248 16.269 16.268-16.27a1.117 1.117 0 0 1 1.566 0Z"></path></svg>'
    tiers = [
        ("insider", "INSIDER", "Free Perks for Every Movie Fan", "Enjoy $5 rewards, 50% off Tickets on Tuesdays & Wednesdays and more. Insiders can earn more free perks by unlocking an AMC Stubs Premiere GO!™ upgrade."),
        ("premiere", "PREMIERE", "It Pays to Plus Up Your Perks", "Never pay online ticket fees! Plus, earn $5 rewards 5X faster than Insiders, and more for just $17.99+tax/year."),
        ("alist", "A-LIST", "See up to 4 Movies Every Week", "Make FREE ticket reservations to watch movies in any format, including Dolby Cinema®, IMAX® and more. Starting at just $19.99+tax/month. <a class=\"stubs-learn\" href=\"/help\">Learn More</a>"),
    ]
    cards = "".join(
        f'''<article class="stubs-tier {slug}"><div class="stubs-tier-head"><img class="stubs-wordmark" src="/local-assets/stubs-logo-{slug}.png" alt="AMC Stubs {label}"><a href="/sign-up?plan={slug}">{'Join<br class="stubs-premiere-break"> Now' if slug == 'premiere' else 'Join Now'}</a></div><h2>{title}</h2><p>{copy}</p></article>'''
        for slug, label, title, copy in tiers
    )
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Create an Account | AMC Theatres</title><link rel="stylesheet" href="/assets/amc.css"></head><body class="stubs-shell"><main><header class="stubs-top"><h1>Create an Account</h1><a href="/" aria-label="Close">{close_icon}</a></header><span class="stubs-test-hook">Join for free</span><section class="stubs-tiers">{cards}</section><p class="stubs-register"><span>?</span> Already joined AMC Stubs at a theatre? <a href="/sign-up?plan=register">Register your account</a> to create a login.</p><section class="stubs-compare"><h2>Compare all Tiers of AMC Stubs</h2><div class="stubs-table"><div>AMC STUBS<br>BENEFITS</div><div>INSIDER</div><div>PREMIERE<br>GO!</div><div>PREMIERE</div><div>A-LIST</div><div>Points Per $1 Spent<br><small>Earn a $5 Reward for Every 5,000 points</small></div><div>20<br><small>POINTS</small></div><div>40<br><small>POINTS</small></div><div>100<br><small>POINTS</small></div><div>100<br><small>POINTS</small></div><div>Rewards Can Be<br>Redeemed For:</div><div>CONCESSIONS</div><div>CONCESSIONS<br>+ TICKETS</div><div>CONCESSIONS<br>+ TICKETS</div><div>CONCESSIONS<br>+ TICKETS</div></div></section></main></body></html>'''
    page = page.replace("<div>Points Per $1 Spent<br><small>", "<div class=\"stubs-key\"><span class=\"stubs-key-title\">Points Per $1 Spent</span><small>")
    page = page.replace("<div>Rewards Can Be<br>Redeemed For:</div>", "<div class=\"stubs-key\"><span class=\"stubs-key-title\">Rewards Can Be<br>Redeemed For:</span><small>(5,000 Points = $5 Reward)</small></div>")
    for points in ("20", "40", "100"):
        page = page.replace(f"<div>{points}<br><small>POINTS</small></div>", f"<div class=\"stubs-points-cell\"><span>{points}</span><small>POINTS</small></div>")
    return with_session(HTMLResponse(page), token, request)


@app.get("/verify-account", response_class=HTMLResponse)
def verify_account_page(request: Request) -> HTMLResponse:
    token, state = session(request)
    body = """<section class="auth-shell"><div class="auth-card"><p class="eyebrow red">Verify your email</p><h1>Enter your local code</h1><p>The local-only verification code is available only to this browser session. No real email is sent.</p><form id="verify-signup-form"><label>Verification code<input name="code" inputmode="numeric" minlength="6" maxlength="6" required></label><button class="button full">Verify and Create Account</button><p class="form-message" role="alert"></p></form></div></section>"""
    return with_session(HTMLResponse(layout("Verify Account", body, state)), token, request)


@app.get("/account", response_class=HTMLResponse)
def account(request: Request) -> HTMLResponse:
    token, state = session(request)
    if not state.get("authenticated"):
        return with_session(RedirectResponse("/login?next=/account", status_code=303), token, request)
    favorites = favorite_slugs(token)
    cards = "".join(poster_card(m, True) for m in MOVIES if m["slug"] in favorites)
    with db() as connection:
        owner = site_owner(connection, token, state)
        orders = connection.execute("SELECT * FROM amc_orders WHERE session_token=? ORDER BY created_at DESC", (owner,)).fetchall()
        membership = connection.execute("SELECT * FROM amc_memberships WHERE session_token=?", (owner,)).fetchone()
    order_html = "".join(
        f'<article class="order-row"><div><p class="eyebrow">Order {esc(o["order_id"][-8:])}</p><h3>{esc(movie(o["movie_slug"])["title"] if movie(o["movie_slug"]) else o["movie_slug"])}</h3><p>{esc(theatre(o["theatre_slug"])["name"] if theatre(o["theatre_slug"]) else o["theatre_slug"])} · {esc(o["showtime"])} · Seats {esc(", ".join(json.loads(o["seats_json"])))}</p><a class="button compact" href="/account/orders/{esc(o["order_id"])}">Manage ticket</a></div><strong>${o["total_cents"]/100:.2f}<br><span class="status">{esc(o["status"])}</span></strong></article>'
        for o in orders
    )
    membership_label = (membership["plan"].replace("alist", "A-List").title() if membership else "Insider")
    preferences = f"""<section class="account-preferences"><h2>Preferences</h2><form id="preferences-form"><label>Preferred theatre<select name="preferred_theatre">{''.join(f'<option value="{esc(t["slug"])}">{esc(t["name"])}</option>' for t in THEATRES)}</select></label><label><input name="notifications_enabled" type="checkbox"> Local reminders</label><label>Privacy<select name="privacy_mode"><option value="standard">Standard</option><option value="minimal">Minimal local storage</option></select></label><button class="button compact">Save preferences</button><p class="form-message" role="status"></p></form></section>"""
    body = f"""<section class="page-head"><div class="wrap account-head"><div><p class="eyebrow red">My AMC</p><h1>Hello, {user_label(state)}</h1><p>AMC Stubs {esc(membership_label)} · {'Active' if membership else 'Local default'}</p></div><button id="logout" class="button outline">Sign Out</button></div></section><section class="account-layout wrap"><aside class="account-sidebar" aria-label="My AMC sections"><strong>My AMC</strong><a href="#overview">Overview</a><a href="#rewards">Rewards</a><a href="#tickets">Tickets &amp; Orders</a><a href="#saved">Saved Movies</a><a href="#profile">Profile &amp; Preferences</a><a href="/track-order">Track an Order</a></aside><div class="account-content"><section id="overview" class="account-summary"><div><span>AMC Stubs tier</span><strong>{esc(membership_label)}</strong></div><div id="rewards"><span>Rewards available</span><strong>$5.00</strong></div><div><span>Points to next reward</span><strong>1,250</strong></div></section><section id="tickets"><div class="section-heading account-orders"><h2>Tickets &amp; Orders</h2></div><div>{order_html or '<div class="empty compact-empty"><p>Your completed sandbox orders will appear here.</p><a href="/showtimes">Find a showtime</a></div>'}</div></section><section id="saved"><h2>Saved Movies</h2><div class="movie-grid">{cards or '<div class="empty compact-empty"><p>You have no saved movies yet.</p><a href="/movies">Browse movies</a></div>'}</div></section><div id="profile">{preferences}</div></div></section>"""
    return with_session(HTMLResponse(layout("My AMC", body, state)), token, request)


@app.get("/account/orders/{order_id}", response_class=HTMLResponse)
def order_detail(order_id: str, request: Request) -> HTMLResponse:
    token, state = session(request)
    if not state.get("authenticated"):
        return with_session(RedirectResponse(f"/login?next=/account/orders/{quote(order_id)}", status_code=303), token, request)
    with db() as connection:
        owner = site_owner(connection, token, state)
        order = connection.execute(
            "SELECT * FROM amc_orders WHERE order_id=? AND session_token=?",
            (order_id, owner),
        ).fetchone()
        metadata = connection.execute(
            "SELECT * FROM amc_order_metadata WHERE order_id=?", (order_id,)
        ).fetchone()
        review = connection.execute(
            "SELECT * FROM amc_reviews WHERE order_id=?", (order_id,)
        ).fetchone()
    if order is None:
        return with_session(HTMLResponse(layout("Order not found", '<section class="empty"><h1>Order not found</h1><a href="/account">Return to My AMC</a></section>', state), status_code=404), token, request)
    film = movie(order["movie_slug"])
    venue = theatre(order["theatre_slug"])
    meta = dict(metadata) if metadata else {"shared_with": "", "reminder_enabled": 0, "concessions_json": "[]", "notes": "", "promo_code": ""}
    review_state = dict(review) if review else {"rating": 5, "body": "", "visibility": "private"}
    concessions = ", ".join(json.loads(meta["concessions_json"])) or "None"
    selected_concessions = set(json.loads(meta["concessions_json"]))
    concession_controls = "".join(
        f'<label class="check-option"><input type="checkbox" value="{esc(value)}" data-manage-concession {"checked" if value in selected_concessions else ""}> {esc(label)}</label>'
        for value, label in (("popcorn", "Popcorn"), ("soft-drink", "Soft drink"), ("candy", "Candy"))
    )
    rating_options = "".join(
        f'<option value="{value}" {"selected" if value == int(review_state["rating"]) else ""}>{value} star{"s" if value != 1 else ""}</option>'
        for value in range(1, 6)
    )
    body = f"""<section class="page-head"><div class="wrap"><p class="eyebrow red">Local sandbox ticket</p><h1>{esc(film['title'] if film else order['movie_slug'])}</h1><p>Order {esc(order_id)} · {esc(order['status'])}</p></div></section><section class="section wrap narrow"><article class="order-ticket"><div class="ticket-code" aria-label="Local ticket code">{esc(order_id[-8:])}</div><dl><div><dt>Theatre</dt><dd>{esc(venue['name'] if venue else order['theatre_slug'])}</dd></div><div><dt>Showtime</dt><dd>{esc(order['showtime'])}</dd></div><div><dt>Seats</dt><dd>{esc(', '.join(json.loads(order['seats_json'])))}</dd></div><div><dt>Ticket type</dt><dd>{esc(order['ticket_type'])}</dd></div><div><dt>Format</dt><dd>{esc(order['format_name'])}</dd></div><div><dt>Attendee</dt><dd>{esc(order['attendee_name'])}</dd></div><div><dt>Concessions</dt><dd>{esc(concessions)}</dd></div><div><dt>Special requests</dt><dd>{esc(meta['notes'] or 'None')}</dd></div><div><dt>Promo</dt><dd>{esc(meta['promo_code'] or 'None')}</dd></div><div><dt>Shared with</dt><dd>{esc(meta['shared_with'] or 'Nobody')}</dd></div><div><dt>Reminder</dt><dd>{'On' if meta['reminder_enabled'] else 'Off'}</dd></div><div><dt>Review</dt><dd>{esc(str(review_state['rating']) + ' stars · ' + review_state['visibility']) if review else 'Not submitted'}</dd></div></dl><div class="order-management" data-order-id="{esc(order_id)}" data-reminder-current="{str(bool(meta['reminder_enabled'])).lower()}"><fieldset><legend>Change showtime</legend><label>New showtime<select data-manage-showtime>{''.join(f'<option>{esc(value)}</option>' for value in SHOWTIMES)}</select></label><button class="button compact" data-order-action="reschedule">Reschedule</button></fieldset><fieldset><legend>Order status</legend><button class="button compact outline" data-order-action="cancel">Cancel</button><button class="button compact outline" data-order-action="refund">Refund</button><button class="button compact outline" data-order-action="reminder">Toggle reminder</button></fieldset><fieldset><legend>Concessions preorder</legend><div class="check-row">{concession_controls}</div><button class="button compact" data-order-action="concessions">Save concessions</button></fieldset><fieldset><legend>Special requests</legend><label>Notes<textarea data-manage-notes maxlength="280">{esc(meta['notes'])}</textarea></label><button class="button compact" data-order-action="notes">Save notes</button></fieldset><fieldset><legend>Promo or voucher</legend><label>Promo code<input data-manage-promo value="{esc(meta['promo_code'])}" placeholder="AMCLOCAL10"></label><button class="button compact" data-order-action="promo">Apply promo</button></fieldset><fieldset><legend>Transfer or share booking</legend><label>Synthetic recipient<input data-manage-recipient type="email" value="{esc(meta['shared_with'])}" placeholder="friend@example.com"></label><button class="button compact" data-order-action="share">Share booking</button></fieldset><fieldset><legend>Review and rating</legend><label>Rating<select data-review-rating>{rating_options}</select></label><label>Visibility<select data-review-visibility><option value="private" {"selected" if review_state['visibility'] == 'private' else ""}>Private</option><option value="public" {"selected" if review_state['visibility'] == 'public' else ""}>Public synthetic review</option></select></label><label>Review<textarea data-review-body maxlength="500">{esc(review_state['body'])}</textarea></label><button class="button compact" data-review-save>Save review</button><p class="form-message" role="status"></p></fieldset><p class="form-message" role="status"></p></div></article><p><a href="/account">← Return to My AMC</a></p></section>"""
    reorder_href = f"/checkout/{quote(order['movie_slug'])}?theatre={quote(order['theatre_slug'])}&amp;time={quote(order['showtime'])}"
    body = body.replace(
        '<div class="ticket-code" aria-label="Local ticket code">',
        f'<p class="ticket-actions"><a class="button compact" data-order-reorder href="{reorder_href}">Book again</a><a class="button compact outline" href="/track-order?order_id={quote(order_id)}">Track order</a></p><div class="ticket-code" aria-label="Local ticket code">',
        1,
    )
    return with_session(HTMLResponse(layout("Sandbox Ticket", body, state)), token, request)


@app.get("/track-order", response_class=HTMLResponse)
def track_order(request: Request, order_id: str = "") -> HTMLResponse:
    token, state = session(request)
    normalized = order_id.strip().upper()
    result = ""
    if normalized:
        if not state.get("authenticated"):
            result = '<div class="empty compact-empty" role="status"><h2>Sign in to track this order</h2><p>Order details are available only to the synthetic local account that created them.</p><a class="button compact" href="/login?next=/track-order">Sign in</a></div>'
        else:
            with db() as connection:
                order = owned_order(connection, token, normalized)
            if order is None:
                result = '<div class="empty compact-empty" role="status"><h2>Order not found</h2><p>Check the local sandbox order number and try again.</p></div>'
            else:
                film = movie(order["movie_slug"])
                venue = theatre(order["theatre_slug"])
                result = f'''<article class="order-row track-result" role="status"><div><p class="eyebrow red">{esc(order["status"])}</p><h2>{esc(film["title"] if film else order["movie_slug"])}</h2><p>{esc(venue["name"] if venue else order["theatre_slug"])} · {esc(order["showtime"])}</p><a class="button compact" href="/account/orders/{quote(normalized)}">Manage ticket</a></div><strong>{esc(normalized)}</strong></article>'''
    body = f'''<section class="page-head"><div class="wrap"><p class="eyebrow red">Local sandbox</p><h1>Track an Order</h1><p>Look up an order stored by this clone. No real AMC order service is contacted.</p></div></section><section class="section wrap narrow"><form class="help-search" action="/track-order"><label for="track-order-id">Sandbox order number</label><input id="track-order-id" name="order_id" value="{esc(normalized)}" placeholder="AMC-XXXXXXXXXXXX" required><button class="button compact">Track order</button></form>{result}</section>'''
    body = body.replace('class="help-search"', 'class="track-form"', 1)
    return with_session(HTMLResponse(layout("Track an Order", body, state)), token, request)


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "") -> HTMLResponse:
    token, state = session(request)
    movies_found = [m for m in MOVIES if q.lower() in (m["title"] + " " + m["genre"]).lower()]
    theatres_found = [t for t in THEATRES if q.lower() in (t["name"] + " " + t["city"] + " " + t["state"]).lower()]
    cards = "".join(poster_card(m, m["slug"] in favorite_slugs(token)) for m in movies_found)
    venue_rows = "".join(f'<article class="theatre-card"><div><h2><a href="/movie-theatres/{t["state"].lower()}/{t["slug"]}">{esc(t["name"])}</a></h2><p>{esc(t["address"])}</p></div></article>' for t in theatres_found)
    body = f"""<section class="page-head"><div class="wrap"><p class="eyebrow red">Search AMC</p><h1>Results for “{esc(q)}”</h1><form class="theatre-search light-search"><input name="q" value="{esc(q)}" required><button class="button">Search</button></form></div></section><section class="section wrap"><h2>Movies ({len(movies_found)})</h2><div class="movie-grid">{cards or '<p>No matching movies.</p>'}</div><h2 class="spaced">Theatres ({len(theatres_found)})</h2><div class="theatre-list">{venue_rows or '<p>No matching theatres.</p>'}</div></section>"""
    return with_session(HTMLResponse(layout("Search", body, state)), token, request)


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request) -> HTMLResponse:
    token, state = session(request)
    body = """<section class="help-hero"><div class="wrap"><h1>How can we help?</h1></div></section><section class="help-actions wrap"><p>Get quick assistance with these self-service options.</p><nav aria-label="Self-service help"><a href="/help?topic=refund">Request a Refund</a><a href="/help?topic=resend">Resend Confirmation Email</a><a href="/account">Manage Communication</a><a href="/help?topic=gift-card">Gift Card Balance</a><a href="/sign-up">Activate Rewards</a></nav><form action="/help" class="help-search"><label for="help-q">Search Help Topics</label><input id="help-q" name="q" placeholder="Search Help Topics" aria-label="Search Help Topics"></form></section><section class="help-topics wrap"><aside><h2>Help Topics</h2></aside><div><h2>Frequently used help topics</h2><details open><summary>How do sandbox tickets work?</summary><p>Choose a movie, theatre, showtime and seats. Completing an approved simulation stores an order only in this clone's local database.</p></details><details><summary>Can I use a real payment card?</summary><p>No. This WebsiteBench clone never requests or sends real payment information.</p></details><details><summary>How do I save a movie?</summary><p>Use the heart button. Your selection is associated with this browser session and remains visible after refresh.</p></details></div></section>"""
    return with_session(HTMLResponse(layout("Help Center", body, state)), token, request)


@app.get("/more", response_class=HTMLResponse)
def more_page(request: Request) -> HTMLResponse:
    token, state = session(request)
    items = [
        ("AMC Stubs", "Compare membership tiers, join, sign in and review your local rewards.", "stubs-bg-insider.jpg", "/sign-up"),
        ("Offers & Promotions", "Browse ticket, member, food and discount offers with their individual actions.", "promo-snack-sip.jpg", "/offers"),
        ("Group Events", "Explore private theatre rentals and group movie experiences.", "theatre-hero-desktop.avif", "/group-events"),
        ("Gift Cards", "Review digital gift-card and local wallet options.", "hero-stubs-desktop.jpg", "/gift-cards"),
        ("Movie Merchandise", "Browse featured collectibles represented in the offline experience.", "promo-pawpatrol-collectibles.jpg", "/merchandise"),
        ("Help Center", "Find refund, confirmation, rewards and account help topics.", "help-hero.avif", "/help"),
    ]
    cards = "".join(
        f'''<article class="offer-card"><img src="/local-assets/{esc(image)}" alt=""><div><p class="eyebrow red">Explore AMC</p><h2>{esc(name)}</h2><p>{esc(copy)}</p><a class="button compact" href="{esc(href)}">Explore</a></div></article>'''
        for name, copy, image, href in items
    )
    body = f'''<section class="page-head dark-head"><div class="wrap"><p class="eyebrow light">More from AMC</p><h1>Explore More Ways to Enjoy the Movies</h1><p>Membership, offers, events, gifts, merchandise and help each have a dedicated destination.</p></div></section><section class="section wrap"><div class="offer-page-grid">{cards}</div></section>'''
    return with_session(HTMLResponse(layout("More", body, state, active="more")), token, request)


@app.get("/password-reset", response_class=HTMLResponse)
def password_reset_page(request: Request) -> HTMLResponse:
    token, state = session(request)
    body = """<section class="auth-shell"><div class="auth-card"><p class="eyebrow red">Account recovery</p><h1>Reset your password</h1><p>Enter the email for a synthetic local account. The response is always the same and no real email is sent.</p><form id="reset-form"><label>Email<input name="email" type="email" required></label><button class="button full">Request Local Reset</button><p class="form-message" role="status"></p></form><p><a href="/login">Return to sign in</a></p></div></section>"""
    return with_session(HTMLResponse(layout("Password Reset", body, state)), token, request)


@app.get("/password-reset/verify", response_class=HTMLResponse)
def password_reset_verify_page(request: Request) -> HTMLResponse:
    token, state = session(request)
    body = """<section class="auth-shell"><div class="auth-card"><p class="eyebrow red">Complete recovery</p><h1>Choose a new password</h1><form id="complete-reset-form"><label>Verification code<input name="code" inputmode="numeric" minlength="6" maxlength="6" required></label><label>New password<input name="new_password" type="password" minlength="8" required></label><button class="button full">Update Local Password</button><p class="form-message" role="alert"></p></form></div></section>"""
    return with_session(HTMLResponse(layout("Complete Password Reset", body, state)), token, request)


class PasswordResetBody(BaseModel):
    email: str = ""


class PasswordResetCompleteBody(BaseModel):
    code: str
    new_password: str


@app.post("/api/password-reset")
def password_reset_request(request: Request, body: PasswordResetBody) -> JSONResponse:
    token, _ = session(request)
    result = auth.start_password_reset(token, email=body.email)
    return with_session(JSONResponse({"ok": True, "message": result["message"]}), token, request)


@app.post("/api/password-reset/complete")
def password_reset_complete(request: Request, body: PasswordResetCompleteBody) -> JSONResponse:
    token, _ = session(request)
    try:
        auth.verify_password_reset_code(token, body.code)
        rotated_token = auth.complete_password_reset(
            token,
            new_password=body.new_password,
            session_rotation_callback=rotate_site_state,
        )
    except Exception:
        return with_session(JSONResponse({"ok": False, "message": "The local code or password is invalid."}, status_code=400), token, request)
    return with_session(JSONResponse({"ok": True, "message": "Password updated in the local sandbox."}), rotated_token, request)


@app.get("/api/local-outbox/password-reset")
def password_reset_outbox(request: Request) -> JSONResponse:
    token, _ = session(request)
    message = auth.local_mail_for_session(token, purpose="password-reset")
    payload = {"ok": True, "message": None}
    if message is not None:
        payload["message"] = {
            "purpose": message["purpose"],
            "recipient": message["recipient"],
            "verification_code": message["verification_code"],
            "status": message["status"],
        }
    return with_session(JSONResponse(payload), token, request)


@app.get("/api/local-outbox/registration")
def registration_outbox(request: Request) -> JSONResponse:
    token, _ = session(request)
    message = auth.local_mail_for_session(token, purpose="registration")
    payload = {"ok": True, "message": None}
    if message is not None:
        payload["message"] = {
            "purpose": message["purpose"],
            "recipient": message["recipient"],
            "verification_code": message["verification_code"],
            "status": message["status"],
        }
    return with_session(JSONResponse(payload), token, request)


@app.post("/api/reset")
def reset_amc_state(request: Request) -> JSONResponse:
    def clear_amc_tables(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM amc_reviews")
        connection.execute("DELETE FROM amc_order_metadata")
        connection.execute("DELETE FROM amc_favorites")
        connection.execute("DELETE FROM amc_orders")
        connection.execute("DELETE FROM amc_preferences")
        connection.execute("DELETE FROM amc_memberships")

    auth.reset_site_state(site_reset=clear_amc_tables, seed_accounts=[SYNTHETIC_ACCOUNT])
    token, state = auth.ensure_session(None)
    response = JSONResponse(
        {
            "ok": True,
            "site_id": SITE_ID,
            "auth_state": "anonymous",
            "authenticated": state["authenticated"],
            "favorites": [],
            "orders": [],
        }
    )
    response.delete_cookie(cookie_name(request), path="/")
    return with_session(response, token, request)


class LoginBody(BaseModel):
    email: str
    password: str
    captcha: bool = True


class SignupBody(BaseModel):
    name: str
    email: str
    password: str
    plan: str = "insider"


class SignupVerifyBody(BaseModel):
    code: str


class FavoriteBody(BaseModel):
    movie_slug: str


class OrderBody(BaseModel):
    movie_slug: str
    theatre_slug: str
    showtime: str
    seats: list[str]
    scenario: str = "sandbox-approved"
    ticket_type: str = "Adult"
    format_name: str = "Standard"
    attendee_name: str = "Local Guest"


class OrderManageBody(BaseModel):
    action: str
    showtime: str = ""
    recipient: str = ""
    reminder_enabled: bool = False
    concessions: list[str] = Field(default_factory=list)
    notes: str = ""
    promo_code: str = ""


class PreferencesBody(BaseModel):
    preferred_theatre: str = "amc-empire-25"
    notifications_enabled: bool = False
    privacy_mode: str = "standard"


class ReviewBody(BaseModel):
    rating: int
    body: str = ""
    visibility: str = "private"


@app.post("/api/login")
def api_login(request: Request, body: LoginBody) -> JSONResponse:
    token, _ = session(request)
    if not body.captcha:
        return with_session(JSONResponse({"ok": False, "message": "Complete the local verification before signing in."}, status_code=400), token, request)
    try:
        state = auth.sign_in(
            token,
            email=body.email,
            password=body.password,
            session_rotation_callback=rotate_site_state,
        )
    except Exception:
        return with_session(JSONResponse({"ok": False, "message": "Email or password is incorrect."}, status_code=400), token, request)
    rotated_token = state["session_token"]
    return with_session(JSONResponse({"ok": True, "display_name": state["account"].get("display_name")}), rotated_token, request)


@app.post("/api/signup")
def api_signup(request: Request, body: SignupBody) -> JSONResponse:
    token, _ = session(request)
    if body.plan not in {"insider", "premiere", "alist", "register"}:
        return with_session(JSONResponse({"ok": False, "message": "Choose a valid local AMC Stubs plan."}, status_code=400), token, request)
    try:
        result = auth.start_registration(
            token,
            email=body.email,
            display_name=body.name,
            password=body.password,
        )
    except Exception:
        status = 409 if auth.account_exists(body.email) else 400
        return with_session(JSONResponse({"ok": False, "message": "Enter unique valid local account details."}, status_code=status), token, request)
    with db() as connection:
        owner = site_owner(connection, token)
        connection.execute(
            "INSERT INTO amc_memberships(session_token,plan,status) VALUES(?,?,?) ON CONFLICT(session_token) DO UPDATE SET plan=excluded.plan,status=excluded.status,updated_at=CURRENT_TIMESTAMP",
            (owner, body.plan, "selected"),
        )
    return with_session(JSONResponse({"ok": True, "verification_required": True, "mail_status": result["mail_status"]}), token, request)


@app.post("/api/signup/verify")
def api_signup_verify(request: Request, body: SignupVerifyBody) -> JSONResponse:
    token, _ = session(request)
    try:
        auth.verify_registration_code(token, body.code)
        state = auth.complete_registration(
            token,
            subject_factory=lambda _connection, _registration: f"amc-{uuid.uuid4().hex}",
            session_rotation_callback=rotate_site_state,
        )
    except Exception:
        return with_session(JSONResponse({"ok": False, "message": "The local verification code is invalid."}, status_code=400), token, request)
    return with_session(JSONResponse({"ok": True}), state["session_token"], request)


@app.post("/api/logout")
def api_logout(request: Request) -> JSONResponse:
    name = cookie_name(request)
    token = request.cookies.get(name)
    auth.sign_out(token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(name, path="/")
    return response


@app.post("/api/favorites")
def api_favorite(request: Request, body: FavoriteBody) -> JSONResponse:
    token, _ = session(request)
    if movie(body.movie_slug) is None:
        return with_session(JSONResponse({"ok": False, "message": "Movie not found."}, status_code=404), token, request)
    with db() as connection:
        owner = site_owner(connection, token)
        exists = connection.execute("SELECT 1 FROM amc_favorites WHERE session_token=? AND movie_slug=?", (owner, body.movie_slug)).fetchone()
        if exists:
            connection.execute("DELETE FROM amc_favorites WHERE session_token=? AND movie_slug=?", (owner, body.movie_slug))
        else:
            connection.execute("INSERT INTO amc_favorites(session_token,movie_slug) VALUES(?,?)", (owner, body.movie_slug))
    return with_session(JSONResponse({"ok": True, "saved": not bool(exists)}), token, request)


@app.post("/api/orders")
def api_order(request: Request, body: OrderBody) -> JSONResponse:
    token, _ = session(request)
    if movie(body.movie_slug) is None or theatre(body.theatre_slug) is None:
        return with_session(JSONResponse({"ok": False, "message": "Movie or theatre not found."}, status_code=404), token, request)
    seats = sorted(set(body.seats))
    if not seats or len(seats) > 8 or any(len(s) not in (2, 3) or s[0] not in "ABCDE" for s in seats):
        return with_session(JSONResponse({"ok": False, "message": "Select between 1 and 8 valid seats."}, status_code=400), token, request)
    if body.scenario == "sandbox-declined":
        return with_session(JSONResponse({"ok": False, "message": "Sandbox payment declined. Choose another simulation."}, status_code=402), token, request)
    if body.scenario == "sandbox-retry":
        return with_session(JSONResponse({"ok": False, "message": "Temporary sandbox error. Please retry."}, status_code=503), token, request)
    if body.scenario != "sandbox-approved":
        return with_session(JSONResponse({"ok": False, "message": "Unknown sandbox scenario."}, status_code=400), token, request)
    ticket_prices = {"Adult": 1599, "Child": 1199, "Senior": 1399}
    format_surcharges = {"Standard": 0, "IMAX": 499, "Dolby Cinema": 399}
    attendee_name = body.attendee_name.strip()
    if body.ticket_type not in ticket_prices or body.format_name not in format_surcharges:
        return with_session(JSONResponse({"ok": False, "message": "Choose a valid ticket type and format."}, status_code=400), token, request)
    if not attendee_name or len(attendee_name) > 80:
        return with_session(JSONResponse({"ok": False, "message": "Enter a synthetic attendee name of 80 characters or fewer."}, status_code=400), token, request)
    order_id = f"AMC-{uuid.uuid4().hex[:12].upper()}"
    total = len(seats) * (ticket_prices[body.ticket_type] + format_surcharges[body.format_name]) + 199
    with db() as connection:
        owner = site_owner(connection, token)
        connection.execute("INSERT INTO amc_orders(order_id,session_token,movie_slug,theatre_slug,showtime,seats_json,total_cents,status,ticket_type,format_name,attendee_name) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (order_id, owner, body.movie_slug, body.theatre_slug, body.showtime, json.dumps(seats), total, "approved", body.ticket_type, body.format_name, attendee_name))
    return with_session(JSONResponse({"ok": True, "order_id": order_id, "total": f"${total/100:.2f}", "message": "Sandbox order confirmed."}), token, request)


def owned_order(connection: sqlite3.Connection, token: str, order_id: str) -> sqlite3.Row | None:
    owner = site_owner(connection, token)
    return connection.execute(
        "SELECT * FROM amc_orders WHERE order_id=? AND session_token=?",
        (order_id, owner),
    ).fetchone()


@app.post("/api/orders/{order_id}/manage")
def api_manage_order(order_id: str, request: Request, body: OrderManageBody) -> JSONResponse:
    token, state = session(request)
    if not state.get("authenticated"):
        return with_session(JSONResponse({"ok": False, "message": "Sign in to manage this order."}, status_code=401), token, request)
    allowed_concessions = {"popcorn", "soft-drink", "candy"}
    action = body.action.strip().lower()
    with db() as connection:
        order = owned_order(connection, token, order_id)
        if order is None:
            return with_session(JSONResponse({"ok": False, "message": "Order not found."}, status_code=404), token, request)
        connection.execute(
            "INSERT OR IGNORE INTO amc_order_metadata(order_id) VALUES(?)", (order_id,)
        )
        if action == "reschedule":
            if body.showtime not in SHOWTIMES or order["status"] in {"cancelled", "refunded"}:
                return with_session(JSONResponse({"ok": False, "message": "Choose an available showtime for an active order."}, status_code=400), token, request)
            connection.execute("UPDATE amc_orders SET showtime=?, status='rescheduled' WHERE order_id=?", (body.showtime, order_id))
        elif action == "cancel":
            if order["status"] == "refunded":
                return with_session(JSONResponse({"ok": False, "message": "A refunded order cannot be cancelled again."}, status_code=409), token, request)
            connection.execute("UPDATE amc_orders SET status='cancelled' WHERE order_id=?", (order_id,))
        elif action == "refund":
            if order["status"] != "cancelled":
                return with_session(JSONResponse({"ok": False, "message": "Cancel the local order before simulating a refund."}, status_code=409), token, request)
            connection.execute("UPDATE amc_orders SET status='refunded' WHERE order_id=?", (order_id,))
        elif action == "share":
            recipient = body.recipient.strip().lower()
            if not recipient.endswith(("@example.com", ".example", ".test")):
                return with_session(JSONResponse({"ok": False, "message": "Use a synthetic .example or .test recipient."}, status_code=400), token, request)
            connection.execute("UPDATE amc_order_metadata SET shared_with=? WHERE order_id=?", (recipient, order_id))
        elif action == "reminder":
            connection.execute("UPDATE amc_order_metadata SET reminder_enabled=? WHERE order_id=?", (int(body.reminder_enabled), order_id))
        elif action == "concessions":
            items = sorted(set(body.concessions))
            if any(item not in allowed_concessions for item in items):
                return with_session(JSONResponse({"ok": False, "message": "Unknown local concession item."}, status_code=400), token, request)
            connection.execute("UPDATE amc_order_metadata SET concessions_json=? WHERE order_id=?", (json.dumps(items), order_id))
        elif action == "notes":
            if len(body.notes) > 280:
                return with_session(JSONResponse({"ok": False, "message": "Notes must be 280 characters or fewer."}, status_code=400), token, request)
            connection.execute("UPDATE amc_order_metadata SET notes=? WHERE order_id=?", (body.notes, order_id))
        elif action == "promo":
            code = body.promo_code.strip().upper()
            if code not in {"", "AMCLOCAL10"}:
                return with_session(JSONResponse({"ok": False, "message": "Promo code is not valid in the local sandbox."}, status_code=400), token, request)
            connection.execute("UPDATE amc_order_metadata SET promo_code=? WHERE order_id=?", (code, order_id))
        else:
            return with_session(JSONResponse({"ok": False, "message": "Unknown order action."}, status_code=400), token, request)
        current = connection.execute("SELECT * FROM amc_orders WHERE order_id=?", (order_id,)).fetchone()
        metadata = connection.execute("SELECT * FROM amc_order_metadata WHERE order_id=?", (order_id,)).fetchone()
    return with_session(JSONResponse({"ok": True, "order": {"order_id": order_id, "status": current["status"], "showtime": current["showtime"], "shared_with": metadata["shared_with"], "reminder_enabled": bool(metadata["reminder_enabled"]), "concessions": json.loads(metadata["concessions_json"]), "notes": metadata["notes"], "promo_code": metadata["promo_code"]}}), token, request)


@app.post("/api/orders/{order_id}/review")
def api_save_review(order_id: str, request: Request, body: ReviewBody) -> JSONResponse:
    token, state = session(request)
    if not state.get("authenticated"):
        return with_session(JSONResponse({"ok": False, "message": "Sign in to review this local order."}, status_code=401), token, request)
    review_text = " ".join(body.body.split())
    if body.rating not in range(1, 6) or len(review_text) > 500 or body.visibility not in {"private", "public"}:
        return with_session(JSONResponse({"ok": False, "message": "Choose 1-5 stars, a valid visibility, and at most 500 characters."}, status_code=400), token, request)
    with db() as connection:
        if owned_order(connection, token, order_id) is None:
            return with_session(JSONResponse({"ok": False, "message": "Order not found."}, status_code=404), token, request)
        connection.execute(
            "INSERT INTO amc_reviews(order_id,rating,body,visibility) VALUES(?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET rating=excluded.rating,body=excluded.body,visibility=excluded.visibility,updated_at=CURRENT_TIMESTAMP",
            (order_id, body.rating, review_text, body.visibility),
        )
    return with_session(JSONResponse({"ok": True, "review": {"order_id": order_id, "rating": body.rating, "body": review_text, "visibility": body.visibility}}), token, request)


@app.get("/api/preferences")
def api_get_preferences(request: Request) -> JSONResponse:
    token, state = session(request)
    if not state.get("authenticated"):
        return with_session(JSONResponse({"ok": False, "message": "Sign in to view preferences."}, status_code=401), token, request)
    with db() as connection:
        owner = site_owner(connection, token, state)
        row = connection.execute("SELECT * FROM amc_preferences WHERE session_token=?", (owner,)).fetchone()
    values = dict(row) if row else {"preferred_theatre": "amc-empire-25", "notifications_enabled": 0, "privacy_mode": "standard"}
    return with_session(JSONResponse({"ok": True, "preferences": {"preferred_theatre": values["preferred_theatre"], "notifications_enabled": bool(values["notifications_enabled"]), "privacy_mode": values["privacy_mode"]}}), token, request)


@app.post("/api/preferences")
def api_save_preferences(request: Request, body: PreferencesBody) -> JSONResponse:
    token, state = session(request)
    if not state.get("authenticated"):
        return with_session(JSONResponse({"ok": False, "message": "Sign in to save preferences."}, status_code=401), token, request)
    if theatre(body.preferred_theatre) is None or body.privacy_mode not in {"standard", "minimal"}:
        return with_session(JSONResponse({"ok": False, "message": "Choose valid local preferences."}, status_code=400), token, request)
    with db() as connection:
        owner = site_owner(connection, token, state)
        connection.execute(
            "INSERT INTO amc_preferences(session_token,preferred_theatre,notifications_enabled,privacy_mode) VALUES(?,?,?,?) ON CONFLICT(session_token) DO UPDATE SET preferred_theatre=excluded.preferred_theatre,notifications_enabled=excluded.notifications_enabled,privacy_mode=excluded.privacy_mode,updated_at=CURRENT_TIMESTAMP",
            (owner, body.preferred_theatre, int(body.notifications_enabled), body.privacy_mode),
        )
    return with_session(JSONResponse({"ok": True, "preferences": body.model_dump()}), token, request)


@app.exception_handler(StarletteHTTPException)
def branded_http_error(request: Request, exc: StarletteHTTPException) -> HTMLResponse | JSONResponse:
    if request.url.path.startswith("/api/"):
        return JSONResponse({"ok": False, "message": str(exc.detail)}, status_code=exc.status_code)
    if exc.status_code != 404:
        return HTMLResponse(str(exc.detail), status_code=exc.status_code)
    token, state = session(request)
    body = '<section class="empty"><p class="eyebrow red">404</p><h1>We could not find that page</h1><p>Try browsing movies, theatres or current showtimes.</p><a class="button" href="/">Return to AMC home</a></section>'
    return with_session(HTMLResponse(layout("Page Not Found", body, state), status_code=404), token, request)


CSS = r"""
@font-face{font-family:Gordita;src:url('/local-fonts/gordita-regular.woff2') format('woff2');font-weight:400;font-style:normal;font-display:swap}
@font-face{font-family:Gordita;src:url('/local-fonts/gordita-medium.woff2') format('woff2');font-weight:500;font-style:normal;font-display:swap}
@font-face{font-family:Gordita;src:url('/local-fonts/gordita-bold.woff2') format('woff2');font-weight:700;font-style:normal;font-display:swap}
@font-face{font-family:Gordita;src:url('/local-fonts/gordita-black.woff2') format('woff2');font-weight:900;font-style:normal;font-display:swap}
:root{--red:#d71920;--dark:#111;--ink:#1b1b1b;--muted:#656565;--line:#ddd;--cream:#f6f4f0;--max:1180px}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);font-family:Arial,Helvetica,sans-serif;background:#fff}a{color:inherit;text-decoration:none}button,input,select{font:inherit}.wrap{width:min(var(--max),calc(100% - 40px));margin:auto}.skip{position:fixed;top:-60px;left:1rem;z-index:99;background:#fff;padding:12px}.skip:focus{top:10px}.utility{background:#171717;color:#ddd;font-size:12px}.utility .wrap{height:30px;display:flex;align-items:center;justify-content:space-between}header{height:76px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0;z-index:30}.nav{height:100%;display:flex;align-items:center;gap:42px}.logo{display:inline-grid;place-items:center;background:var(--red);color:#fff;border-radius:50%;width:70px;height:48px;font-weight:900;font-size:27px;letter-spacing:-3px;transform:rotate(-5deg)}.logo span{transform:rotate(5deg)}.logo.small{width:62px;height:42px;margin-bottom:20px}.nav nav{display:flex;align-self:stretch}.nav nav a{padding:0 19px;display:flex;align-items:center;font-weight:700;border-bottom:4px solid transparent}.nav nav a:hover,.nav nav a.on{border-color:var(--red)}.nav-actions{margin-left:auto;display:flex;gap:18px;align-items:center}.icon-button{border:0;background:none;font-size:30px;cursor:pointer}.account{font-weight:700}.search-panel{position:fixed;z-index:29;top:106px;left:0;right:0;background:#fff;border-bottom:1px solid #bbb;box-shadow:0 10px 30px #0002;padding:30px}.search-panel form{max-width:760px;margin:auto}.search-panel label{font-weight:700}.search-panel form div,.theatre-search{display:flex;gap:10px;margin-top:10px}.search-panel input,.theatre-search input{flex:1;padding:15px;border:1px solid #999}.search-panel button{background:#222;color:#fff;border:0;padding:0 24px}.hero{min-height:540px;background:radial-gradient(circle at 76% 44%,#376f89 0 5%,#17334f 25%,#07101b 52%,#020304 75%);color:#fff;display:flex;align-items:center;position:relative;overflow:hidden}.hero:after{content:"F1";position:absolute;right:4%;font-size:280px;line-height:1;font-weight:900;font-style:italic;color:#ffffff0c;transform:skew(-10deg)}.hero-content{position:relative;z-index:2}.hero h1{font-size:clamp(43px,6vw,78px);line-height:.95;max-width:800px;margin:12px 0 22px;letter-spacing:-3px}.hero p:not(.eyebrow){font-size:21px;max-width:620px}.eyebrow{text-transform:uppercase;letter-spacing:1.7px;font-size:12px;font-weight:900;color:#555}.eyebrow.red{color:var(--red)}.eyebrow.light{color:#fff}.button{display:inline-flex;align-items:center;justify-content:center;background:var(--red);color:#fff;border:2px solid var(--red);border-radius:2px;padding:14px 22px;font-weight:800;cursor:pointer;min-height:48px}.button:hover{background:#b91016;border-color:#b91016}.button.white{background:#fff;border-color:#fff;color:#111}.button.outline{background:#fff;color:#111;border-color:#222}.button.outline-light{background:transparent;color:#fff;border-color:#fff}.button.compact{padding:9px 13px;min-height:38px;font-size:13px}.button.full{width:100%}.button:disabled{opacity:.45;cursor:not-allowed}.text-link{font-weight:800;margin-left:20px}.text-link.light{color:#fff}.finder{background:var(--cream);padding:30px 0;border-bottom:1px solid #ddd}.finder h2{font-size:24px;margin-top:0}.finder-form,.filter-bar{display:grid;grid-template-columns:1.3fr 1fr 1fr auto;gap:14px;align-items:end}.finder-form label,.filter-bar label,.auth-card label,.order-card label{display:flex;flex-direction:column;gap:7px;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.8px}.finder-form input,.finder-form select,.filter-bar input,.filter-bar select,.auth-card input,.order-card select{height:48px;border:1px solid #aaa;padding:0 12px;background:#fff}.section{padding-top:60px;padding-bottom:70px}.section-heading{display:flex;align-items:end;justify-content:space-between;margin-bottom:25px}.section-heading h2,.section h2{font-size:32px;margin:6px 0}.section-heading a{font-weight:800;color:var(--red)}.movie-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:28px 18px}.poster{aspect-ratio:2/3;background:linear-gradient(155deg,#ffffff18,#0008),var(--poster);color:#fff;display:flex;flex-direction:column;justify-content:flex-end;padding:22px;box-shadow:0 5px 15px #0003;position:relative;overflow:hidden}.poster:before{content:"";position:absolute;width:180px;height:180px;border:40px solid #ffffff10;border-radius:50%;top:-40px;right:-70px}.poster strong{font-size:25px;line-height:1;position:relative;text-transform:uppercase}.poster small{margin-top:12px;position:relative}.poster-kicker{position:absolute;top:20px;left:20px;font-size:14px;font-weight:900;border:2px solid #fff;border-radius:50%;padding:7px}.card-copy{padding:12px 2px}.card-copy h3{margin:4px 0 13px;font-size:18px}.card-actions{display:flex;justify-content:space-between;align-items:center}.heart{border:1px solid #aaa;background:#fff;width:40px;height:38px;font-size:22px;cursor:pointer;color:#777}.heart.saved,.heart-detail.saved{color:var(--red);border-color:var(--red)}.offers{background:#151515;color:#fff;padding:65px 0}.offer-grid{display:grid;grid-template-columns:1fr 1fr;gap:28px}.offer-grid article{padding:45px;background:linear-gradient(135deg,#b4141a,#601014)}.offer-grid article+article{background:linear-gradient(135deg,#5a351c,#17120f)}.offer-grid h2{font-size:38px;margin:12px 0}.offer-grid p{font-size:18px;line-height:1.6}.page-head{background:var(--cream);padding:62px 0 50px;border-bottom:1px solid #ddd}.page-head h1{font-size:54px;letter-spacing:-2px;margin:8px 0}.page-head p{max-width:760px;font-size:18px;line-height:1.55}.dark-head,.theatre-hero{background:#151515;color:#fff}.theatre-search{max-width:720px}.result-count{color:var(--muted);font-weight:700}.filter-bar{padding:22px;background:var(--cream);border:1px solid #ddd}.empty{grid-column:1/-1;text-align:center;padding:70px 20px;background:#f7f7f7}.compact-empty{padding:30px}.detail-hero{background:linear-gradient(115deg,#0c0c0c 20%,var(--poster));color:#fff;padding:70px 0}.detail-grid{display:grid;grid-template-columns:260px 1fr;gap:60px;align-items:center}.poster.large{width:260px}.detail-grid h1{font-size:58px;margin:10px 0}.metadata{font-weight:800}.lede{font-size:19px;line-height:1.65;max-width:700px}.lede.dark{color:#444}.score{display:flex;align-items:center;gap:12px;margin:24px 0}.score strong{font-size:34px}.score span{max-width:90px;font-size:12px;text-transform:uppercase}.narrow{max-width:860px}.showtime-grid{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 40px}.showtime{border:1px solid #222;padding:11px 15px;font-weight:800;background:#fff}.showtime:hover{background:#111;color:#fff}.theatre-list,.listing-list{display:grid;gap:18px}.theatre-card,.venue-block,.listing,.order-row{border:1px solid #d4d4d4;padding:24px;background:#fff}.theatre-card{display:flex;justify-content:space-between;align-items:center;gap:20px}.theatre-card h2,.venue-block h2,.listing h2{margin:4px 0}.chips{display:flex;flex-wrap:wrap;gap:8px}.chips span{background:#eee;padding:7px 10px;font-size:12px;font-weight:700}.light-chips span{background:#ffffff18}.date-tabs{display:flex;overflow:auto;border-bottom:1px solid #aaa;margin-bottom:30px}.date-tabs a{padding:16px 22px;font-weight:800;white-space:nowrap}.date-tabs a.on{color:var(--red);border-bottom:4px solid var(--red)}.listing{display:grid;grid-template-columns:250px 1fr;gap:20px;align-items:center}.venue-block>p{color:#666}.showtime-row{display:grid;grid-template-columns:230px 1fr;gap:20px;padding:25px 0;border-top:1px solid #ddd;align-items:center}.showtime-row h3{margin:0}.showtime-row .showtime-grid{margin:0}.showtime-filter{margin-top:30px}.checkout-head{background:#171717;color:#fff;padding:40px 0}.checkout-head h1{font-size:40px;margin:15px 0 5px}.checkout-grid{display:grid;grid-template-columns:1fr 360px;gap:50px;padding-top:60px;padding-bottom:80px}.screen{background:linear-gradient(#eee,#fff);border-top:8px solid #888;text-align:center;padding:18px;color:#777;letter-spacing:8px;margin:40px 0}.seat-map{display:grid;grid-template-columns:repeat(8,1fr);gap:12px;max-width:640px;margin:auto}.seat{border:2px solid #777;background:#fff;border-radius:8px 8px 3px 3px;height:42px;font-size:11px;cursor:pointer}.seat.selected{background:var(--red);color:#fff;border-color:var(--red)}.seat-legend{display:flex;justify-content:center;gap:30px;margin-top:25px}.order-card{border:1px solid #ccc;padding:25px;align-self:start;position:sticky;top:130px}.order-card h2{margin-top:0}.order-card dl div{display:flex;justify-content:space-between;gap:20px;border-bottom:1px solid #ddd;padding:12px 0}.order-card dt{font-weight:800}.order-card dd{text-align:right;margin:0}.order-card .total{font-size:21px}.fine-print,.demo-note{font-size:12px;color:#666;line-height:1.5}.auth-shell{min-height:680px;background:linear-gradient(135deg,#171717,#4e0e11);padding:65px 20px}.auth-card{background:#fff;max-width:480px;margin:auto;padding:42px;box-shadow:0 20px 60px #0007}.auth-card h1{font-size:38px;margin:8px 0}.auth-card form{display:grid;gap:18px;margin-top:30px}.auth-switch{text-align:center;margin-top:26px}.auth-switch a{color:var(--red);font-weight:800}.form-message{min-height:20px;color:#b00020;margin:0}.account-head{display:flex;justify-content:space-between;align-items:center}.order-row{display:flex;justify-content:space-between;align-items:center}.order-row h3{margin:4px 0}.order-row strong{text-align:right}.status{color:#16733a;text-transform:uppercase;font-size:12px}.account-orders{margin-top:60px}.spaced{margin-top:60px!important}details{border-bottom:1px solid #ccc;padding:20px 0}summary{font-size:20px;font-weight:800;cursor:pointer}details p{line-height:1.7;color:#555}footer{background:#080808;color:#ddd;padding:55px 0 25px}.footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:30px}.footer-grid h3{color:#fff}.footer-grid a{display:block;margin:12px 0}.copyright{text-align:center;color:#777;border-top:1px solid #333;margin:35px auto 0;padding-top:20px;font-size:12px}#toast{position:fixed;right:22px;bottom:22px;background:#111;color:#fff;padding:14px 20px;transform:translateY(100px);opacity:0;transition:.25s;z-index:99;max-width:360px}#toast.show{transform:none;opacity:1}@media(max-width:900px){.nav nav{display:none}.movie-grid{grid-template-columns:repeat(2,1fr)}.finder-form,.filter-bar{grid-template-columns:1fr 1fr}.detail-grid,.checkout-grid,.listing,.showtime-row{grid-template-columns:1fr}.order-card{position:static}.offer-grid{grid-template-columns:1fr}}@media(max-width:560px){.utility{display:none}header{top:0}.wrap{width:min(100% - 24px,var(--max))}.nav{gap:12px}.account{font-size:0}.account:before{content:"Account";font-size:14px}.logo{width:57px;height:40px;font-size:23px}.hero{min-height:500px}.hero h1,.page-head h1,.detail-grid h1{font-size:40px}.movie-grid{grid-template-columns:1fr 1fr;gap:20px 10px}.poster{padding:12px}.poster strong{font-size:17px}.poster-kicker{top:10px;left:10px}.finder-form,.filter-bar{grid-template-columns:1fr}.detail-grid{gap:25px}.poster.large{width:210px}.checkout-grid{gap:25px}.seat-map{gap:6px}.seat{font-size:9px}.theatre-card,.order-row{align-items:flex-start;flex-direction:column}.footer-grid{grid-template-columns:1fr 1fr}.footer-grid>div:first-child{grid-column:1/-1}.search-panel{top:76px}}
.order-card input{height:48px;border:1px solid #aaa;padding:0 12px;background:#fff}
/* Current public shell, based only on supplied sanitized observations. */
body{overflow-x:hidden}:root{--max:1248px}.alert-strip{height:42px;background:#d71920;color:#fff;display:grid;place-items:center;text-align:center;font-weight:800;font-size:13px;padding:0 12px}.mobile-menu{display:none}header{height:58px;background:#050505;border:0;position:relative}.nav{color:#fff}.logo{background:transparent;border-radius:0;width:86px;height:58px;transform:none;color:#e31b23;font-size:31px;letter-spacing:-3px}.logo span{transform:none}.logo small{display:block;color:#fff;font-size:7px;letter-spacing:2px;text-align:center;margin-top:-4px}.nav nav a{font-size:15px}.nav-actions .icon-button{color:#fff}.subnav{height:34px;background:#050505;color:#ddd;font-size:11px}.subnav .wrap{display:flex;height:100%;gap:25px;align-items:center}.subnav .wrap span{flex:1}.search-panel{top:100px}.hero{height:450px;min-height:450px;background-image:linear-gradient(90deg,#000 0%,#000b 38%,#0002 70%),url('/local-assets/hero-insidious.jpg');background-size:cover;background-position:center;color:#fff}.hero:after{display:none}.hero h1{font-size:48px;line-height:1;letter-spacing:-1px;max-width:600px}.hero p:not(.eyebrow){font-size:16px;line-height:1.5;max-width:480px}.carousel-controls{position:absolute;left:50%;bottom:18px;transform:translateX(-50%);display:flex;align-items:center;gap:11px}.carousel-controls button{border:0;background:transparent;color:#fff;font-size:28px;cursor:pointer}.carousel-controls .dot{width:9px;height:9px;border:1px solid #fff;border-radius:50%;padding:0}.carousel-controls .dot.on{background:#fff}.movies-home{height:906px;background:linear-gradient(#07191ddd,#07191ddd),url('/local-assets/movies-bg.jpg') center top/cover;color:#fff;padding:34px 0 72px}.movies-title{display:flex;align-items:end;justify-content:space-between;border-bottom:1px solid #ffffff88;margin-bottom:58px}.movies-title h2{font-size:34px;margin:0 0 14px}.movies-title button{border:0;border-bottom:4px solid transparent;background:none;color:#fff;padding:18px 15px 13px;font-weight:800;cursor:pointer}.movies-title button.on{border-color:#e31b23}.movie-rail{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:20px}.movies-home .movie-card:nth-child(n+6){display:none}.movies-home .poster{background-size:cover;background-position:center}.movies-home .card-copy .eyebrow{color:#ccc}.rail-more{margin-top:45px}.app-promo{height:221px;background:linear-gradient(115deg,#73131a,#1b090a);color:#fff;display:flex;align-items:center}.app-grid{display:grid;grid-template-columns:1fr 1fr;align-items:center;gap:70px}.app-grid h2{font-size:34px;margin:8px 0;max-width:650px}.app-grid p{font-size:16px;line-height:1.5}.home-promotion{height:585px;display:grid;grid-template-columns:1fr 1fr;background:#f3f0e9}.home-promotion.reverse .promotion-image{order:2}.promotion-image{background-size:cover;background-position:center}.promotion-copy{display:flex;flex-direction:column;justify-content:center;align-items:flex-start;padding:70px max(48px,calc((100vw - 1248px)/2));padding-right:70px}.home-promotion.reverse .promotion-copy{padding-left:max(48px,calc((100vw - 1248px)/2));padding-right:70px}.promotion-copy h2{font-size:48px;line-height:1.04;letter-spacing:-1.5px;margin:10px 0 20px;max-width:510px}.promotion-copy p:not(.eyebrow){font-size:18px;line-height:1.6;max-width:500px}.offers-cta{height:118px;background:#d71920;color:#fff}.offers-cta .wrap{height:100%;display:flex;align-items:center;justify-content:space-between}.offers-cta h2{font-size:30px}.pre-footer-space{height:64px}footer{height:876px}.footer-grid{grid-template-columns:1.5fr 1fr 1fr 1fr;min-height:720px}.date-tabs button{padding:16px 22px;font-weight:800;white-space:nowrap;border:0;background:#fff;cursor:pointer}.date-tabs button.on{color:var(--red);border-bottom:4px solid var(--red)}
@media(max-width:900px){.movie-rail{grid-template-columns:repeat(3,1fr)}.movies-home .movie-card:nth-child(n+4){display:none}.app-grid{grid-template-columns:1fr 1fr}.home-promotion{grid-template-columns:1fr 1fr}.promotion-copy{padding:45px 30px}.footer-grid{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.alert-strip{height:76px;line-height:1.35}.subnav{display:none}header{height:39px}.nav{width:100%;padding:0 8px;gap:5px}.mobile-menu{display:block;color:#fff;font-size:16px}.logo{position:absolute;left:50%;transform:translateX(-50%);width:95px;height:38px;font-size:21px}.logo small{font-size:5px}.nav-actions{gap:4px}.nav-actions .icon-button{font-size:19px}.account:before{content:"Showtimes";font-size:9px}.search-panel{top:115px}.nav.open nav{display:flex;position:absolute;top:39px;left:0;right:0;background:#111;flex-direction:column;height:auto;padding:15px;z-index:40}.nav.open nav a{padding:12px}.hero{height:450px;min-height:450px;background-position:64% center;align-items:end}.hero-content{padding-bottom:64px;background:linear-gradient(0deg,#000d,#0000);width:100%}.hero h1{font-size:34px;margin:8px 0 15px}.hero p:not(.eyebrow){font-size:14px;max-width:330px}.carousel-controls{bottom:13px}.movies-home{height:auto;min-height:810px;padding:31px 0 60px}.movies-title{display:block;margin-bottom:67px}.movies-title h2{font-size:28px;margin-left:4px}.movies-title div{display:flex}.movies-title button{font-size:12px;padding:10px 7px}.movie-rail{display:flex;gap:16px;overflow:auto;padding:0 26px 18px;margin:0 -12px;scroll-snap-type:x mandatory}.movies-home .movie-card{display:block!important;min-width:264px;scroll-snap-align:start}.movies-home .movie-card:nth-child(n+5){display:none!important}.poster{background-size:cover;background-position:center}.app-promo{height:auto;padding:38px 0}.app-grid{grid-template-columns:1fr;text-align:center;gap:10px}.home-promotion,.home-promotion.reverse{height:auto;min-height:640px;grid-template-columns:1fr}.home-promotion .promotion-image,.home-promotion.reverse .promotion-image{order:0;min-height:330px}.promotion-copy,.home-promotion.reverse .promotion-copy{padding:42px 24px}.promotion-copy h2{font-size:36px}.offers-cta{height:auto;padding:28px 0}.offers-cta .wrap{align-items:flex-start;flex-direction:column;gap:15px}.pre-footer-space{height:32px}footer{height:auto}.footer-grid{min-height:0;grid-template-columns:1fr 1fr}.footer-grid>div:first-child{grid-column:1/-1}.footer-grid h3{font-size:14px}.footer-grid a{font-size:12px}.page-head{padding:42px 0}.page-head h1{font-size:38px}}
/* Public home-shell visual contract.  The rules below deliberately override the
   generic application shell without changing detail, auth or checkout pages. */
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.alert-strip{position:relative;background:#e12839;justify-items:start;padding-left:96px}.alert-strip a{text-decoration:underline}.alert-close{position:absolute;right:96px;top:8px;border:0;background:transparent;color:#fff;font-size:28px;line-height:26px;cursor:pointer}.mobile-tools,.mobile-search{display:none}
header,.subnav{background:#000}.logo{width:70px;place-items:center start}.logo span{text-align:center}.nav{background:#000}header .nav{width:calc(100% - 64px);max-width:none;gap:16px}.nav nav a{padding:0 10px}.header-search{margin-left:auto;width:240px;height:34px;display:flex;background:#171d21;border-radius:7px;overflow:hidden}.header-search input{min-width:0;flex:1;border:0;background:transparent;color:#fff;padding:0 12px;font-size:13px}.header-search button{width:36px;border:0;background:transparent;color:#8a9aa3}.nav-actions{margin-left:0;gap:18px}.showtimes-link{font-weight:800;font-size:14px}.showtimes-link:before{content:"♧";font-size:22px;margin-right:8px}.account{white-space:nowrap}.subnav .wrap{width:calc(100% - 64px);max-width:none}.theatre-location{font-size:14px}
.button{background:#cc1f2e;border-color:#cc1f2e}.hero{align-items:flex-start;background-position:100% center;background-size:cover}.hero-content{padding-top:173px}.hero h1{font-size:40px;line-height:1.06;letter-spacing:-1.6px;max-width:760px;margin:5px 0 12px}.hero p:not(.eyebrow){font-size:20px;line-height:1.4;max-width:750px;margin:0 0 25px}.hero-button{border-radius:999px;min-width:143px;white-space:nowrap}.carousel-controls{bottom:14px;z-index:3}
.movies-home{position:relative;isolation:isolate;background:none}.movies-home:before{content:"";position:absolute;inset:0;z-index:-1;background:radial-gradient(ellipse 300px 760px at 28% 48%,#414146 0%,#303338 42%,transparent 100%),radial-gradient(ellipse 520px 520px at 3% 0%,#12303f 0%,#0d222c 45%,transparent 100%),radial-gradient(ellipse 500px 420px at 73% 0%,#16333a 0%,transparent 75%),#071312}.movies-title{margin-bottom:87px}.movies-title h2{font-size:40px;letter-spacing:-1.5px}.movie-rail{grid-template-columns:292px 278px 306px 278px 278px;gap:76px;margin-left:-251px}.movies-home .movie-card:nth-child(1) .poster,.movies-home .movie-card:nth-child(2) .poster,.movies-home .movie-card:nth-child(n+4) .poster{width:278px}.movies-home .movie-card:nth-child(3) .poster{width:306px}.movies-home .poster:before,.movies-home .poster-kicker,.movies-home .poster>strong,.movies-home .poster>small{display:none}
@media(max-width:560px){
  .alert-strip{display:flex;align-items:center;justify-content:flex-start;text-align:left;padding:0 48px 0 16px;font-size:14px;line-height:17px}.alert-strip span{max-width:334px}.alert-close{right:12px;top:27px;font-size:26px}
  header{border-bottom:1px solid #780e1a}header .nav{width:100%;max-width:none;margin:0;padding:0 12px;gap:0;justify-content:space-between;transform:translateY(-4px)}.mobile-tools{display:flex;align-items:center;gap:12px}.mobile-menu,.mobile-search{display:block;padding:0;color:#fff;font-size:21px;line-height:1}.mobile-search{font-size:24px}.header-search{display:none}.logo{width:72px;height:39px}.nav-actions{margin-left:auto;gap:12px}.showtimes-link{font-size:10px}.showtimes-link:before{font-size:15px;margin-right:4px}.account{font-size:0}.account:before{content:""}.account:after{content:"◎";font-size:21px;color:#fff}.account span{display:none}
  .logo{width:94px;font-size:34px;place-items:center}.hero{align-items:flex-start;background-color:#000;background-image:linear-gradient(180deg,#0003 0%,transparent 18%),linear-gradient(90deg,#0008 0%,transparent 29%,transparent 73%,#0008 100%),linear-gradient(0deg,#000 0%,#000b 10%,#0005 30%,transparent 60%),url('/local-assets/hero-insidious-mobile.jpg');background-position:center;background-size:cover;background-repeat:no-repeat}.hero-content{padding:121px 16px 0;background:transparent;margin:0;width:100%}.hero h1{font-size:32px;line-height:1.04;letter-spacing:-1px;max-width:360px;margin:6px 0 7px}.hero p:not(.eyebrow){font-size:18px;line-height:1.45;max-width:358px;margin:0 0 20px}.hero-button{width:131px;min-width:131px;border-radius:999px;white-space:nowrap;padding-left:14px;padding-right:14px}.carousel-controls{bottom:6px;gap:5px}.carousel-controls button{font-size:24px}.carousel-controls .dot{width:9px;height:9px}
  .movies-home{background:#000;min-height:881px;padding-top:31px}.movies-home:before{display:none}.movies-title{margin-bottom:62px}.movies-title h2{font-size:32px;letter-spacing:-1px;margin:0}.movies-title div{margin-top:0}.movies-title button{font-size:16px;padding:3px 3px 9px;margin-right:8px}.movie-rail{display:flex;gap:16px;overflow:auto;padding:0 30px 18px;margin:0 -12px;transform:translateX(43px)}.movies-home .movie-card{min-width:306px}.movies-home .movie-card:nth-child(3){order:-1;margin-left:0}.movies-home .poster{width:306px!important}
}
.movies-home{overflow:hidden}
/* Exact public carousel typography and overlay, using only localized public assets. */
body{font-family:Gordita,Helvetica,sans-serif}
.alert-strip{height:41.5px;background:#e12839;font-size:14px;font-weight:500;line-height:17.5px}.alert-strip:after{content:"";position:absolute;left:0;right:0;bottom:0;height:.5px;background:#000;pointer-events:none}.alert-copy a,.alert-copy strong{font-weight:700}.alert-copy strong{font-size:14px}.alert-close{right:112px;top:12.75px;width:16px;height:16px;padding:0;font-size:0;line-height:16px}
body>header{background:#000}body>header .nav{width:100%;margin:0;padding:0 40px 0 32px;background:linear-gradient(90deg,#000 0%,#000 85%,#340c43 100%)}header .nav nav a{transform:translateY(1px)}
.logo{width:80px}.logo>img{display:block;width:80px;height:auto}.logo>span{display:none}header{height:60px}.subnav{height:32px}header .nav{width:calc(100% - 72px);margin-left:32px;margin-right:40px;gap:16px}.nav nav{gap:16px;align-items:center}.nav nav a{height:47px;padding:12px 0;font-size:14px;font-weight:500;line-height:21px}.nav nav a[href="/help"]{display:flex;gap:8px}.nav nav a[href="/help"]:after{content:"";width:11px;height:11px;border-right:1px solid #fff;border-bottom:1px solid #fff;transform:rotate(45deg) translateY(-2px)}
.header-search{position:relative;width:240px;height:32px}.header-search input{width:100%;height:32px;padding:8px 32px 8px 12px;font-size:12px;line-height:18px}.header-search button{position:absolute;right:12px;top:8px;width:16px;height:16px;padding:0}.header-search button img{display:block;width:16px;height:16px}
.showtimes-link,.account{display:flex;align-items:flex-start}.nav-actions{gap:16px}.showtimes-link:before{display:none}.showtimes-link{height:29.039px;font-size:14px;font-weight:500;line-height:21px}.showtimes-link img{width:24px;height:23.039px;margin:0 8px 4px 0}.showtimes-link>span{transform:translateY(3px)}.account{width:64.078px;height:49.039px;padding:12px 0;overflow:hidden;font-size:14px;font-weight:500;line-height:21px}.account img{flex:none;width:24px;height:23.039px;margin-right:8px}.account span{display:inline-block;font-size:0;transform:translateY(1px)}.account span:after{content:"??";font-size:14px}.account .account-chevron{width:12px;height:12px;margin:5.5px 0 0 4px}.alert-close img,.mobile-search img{display:block;width:100%;height:100%}
.subnav .wrap{width:calc(100% - 72px);margin-left:32px;margin-right:40px;gap:16px}.subnav .wrap>a{font-size:12px;line-height:18px;color:#fff}.theatre-location,.sub-get-tickets{display:flex;align-items:center;gap:8px}.theatre-location img{width:18px;height:18px}.sub-get-tickets{margin-left:-4px;color:#1ab7fd!important}.sub-get-tickets img{width:12px;height:18px;margin-left:-4px}
.hero{align-items:flex-end;background-image:radial-gradient(transparent 50%,#000 100%),linear-gradient(45deg,#000,transparent 50%),url('/local-assets/hero-stubs-desktop.jpg');background-position:right center;background-size:cover;background-repeat:no-repeat}
.hero-content{margin:0 auto;padding:0;background:none}
.hero-grid{display:grid;gap:8px;width:60%;height:241.890625px;padding-bottom:40px}
.hero-grid header{height:auto;background:transparent;border:0;position:static}
.hero-grid header,.hero-grid p,.hero-title{margin:0;padding:0}
.hero-grid .eyebrow{font-size:14px;font-weight:500;line-height:17.5px;letter-spacing:normal}
.hero-title{font-size:36px;font-weight:900;line-height:45px;letter-spacing:-1.08px}
.hero-description{height:75.390625px;font-size:18px;font-weight:400;line-height:29.7px}
.hero-actions{height:48px;display:flex}
.hero-button{height:48px;min-height:48px;min-width:142.8984375px;border:0;border-radius:9999px;padding:0 24px;background:#ce0e2d;font-size:16px;font-weight:700;line-height:24px}
.movies-home{padding-top:0;background:#000}.movies-home:before{background:url('/local-assets/movies-exact.avif') center/cover no-repeat;opacity:.5}
.movies-title{box-sizing:border-box;height:87px;margin-bottom:66.2px;padding:32px 0 8px;border-bottom:2px solid #a8b8bc;align-items:center}
.movies-title h2{font-size:36px;font-weight:900;line-height:45px;letter-spacing:-1.08px;margin:0}
.movies-title div{display:flex;gap:12px}
.movies-title button{height:24px;margin:0;padding:0;border:0;font-size:16px;font-weight:500;line-height:24px;color:#a8b8bc}
.movies-title button.on{color:#fff;text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:8px}
.movies-home .poster{opacity:.6}.movies-home .movie-card:not(:nth-child(3)){padding-top:29.8046875px}
@media(max-width:560px){
  .alert-strip{height:76.5px;background:#e12839;font-size:14px;font-weight:500;line-height:17.5px}.alert-strip .alert-copy{display:block;flex:none;width:334px;max-width:334px}.alert-strip:after{display:none}body>header{height:38px;background:#000}body>header .nav{width:100%;margin:0;padding:4px;background:#000}.alert-copy a,.alert-copy strong{font-weight:700}.alert-copy strong{font-size:14px}
  .alert-close{right:16px;top:30.25px;width:16px;height:16px;padding:0;font-size:0}
  header .nav{display:grid;grid-template-columns:1fr 64px 1fr;width:100%;height:38px;margin:0;padding:4px;gap:0;transform:none}
  .mobile-tools{display:flex;align-items:center;gap:4px}.mobile-menu{width:36px;height:30px;padding:7px 8px}.menu-lines{display:grid;gap:4px}.menu-lines i{display:block;width:20px;height:2px;background:#fff}.mobile-search{width:24px;height:24px;padding:4px}
  .logo{position:static;display:flex;width:64px;height:30px;transform:none}.logo>img{width:64px;height:30px}
  .nav-actions{display:flex;justify-content:flex-end;align-items:center;gap:12px;margin:0}.showtimes-link{width:83px;height:23.039px;font-size:10px;font-weight:400;line-height:15px;gap:4px}.showtimes-link:before{display:none}.showtimes-link>span{transform:none}.showtimes-link img{width:24px;height:23.039px;margin:0}.account{width:32px;height:23.039px;padding:0}.account:after{display:none}.account img{width:24px;height:23.039px;margin:0 8px 0 0}.account .account-chevron{display:none}
  .hero{align-items:flex-end;background-image:radial-gradient(transparent 50%,#000 100%),linear-gradient(45deg,#000,transparent 50%),url('/local-assets/hero-insidious-mobile.jpg');background-position:center;background-size:cover}
  .hero-content{width:100%;margin:0;padding:0 16px}
  .hero-grid{width:100%;height:313.09375px;padding-bottom:0}
  .hero-title{font-size:28px;line-height:35px;letter-spacing:-.84px;text-wrap:balance}
  .hero-description{height:121.59375px;font-size:16px;line-height:26.4px}
  .hero-actions{margin-bottom:40px}
  .hero-button{width:131.0390625px;min-width:131.0390625px;font-size:14px;line-height:21px}
  .movies-home{padding-top:0}
  .movies-home>.wrap{width:100%;margin:0}
  .movies-title{box-sizing:border-box;width:calc(100% - 32px);height:101px;margin:0 16px 66px;padding:32px 0 8px;border-bottom:2px solid #a8b8bc;display:flex;flex-wrap:wrap;column-gap:48px}
  .movies-title h2{width:max-content;max-width:90vw;font-size:28px;font-weight:900;line-height:35px;letter-spacing:-.84px}
  .movies-title div{display:flex;gap:12px;width:100%}
  .movies-title button{height:24px;margin:0;padding:0;border:0;font-size:16px;font-weight:500;line-height:24px;color:#a8b8bc}
  .movies-title button.on{color:#fff;text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:8px}
  .movie-rail{margin:0;padding:0 0 18px;transform:translateX(42px)}
  .movies-home .poster{opacity:1}.movies-home .movie-card:not(:nth-child(3)){padding-top:0}
}
.account-preferences{margin-top:60px;padding:28px;border:1px solid #d4d4d4}.account-preferences form{display:flex;flex-wrap:wrap;align-items:end;gap:12px}.account-preferences label,.order-management label{display:flex;flex-direction:column;gap:6px;font-size:12px;font-weight:700}.account-preferences select,.order-management select,.order-management input{height:40px;padding:0 10px}.order-ticket{padding:32px;border:1px solid #d4d4d4}.order-ticket dl>div{display:flex;justify-content:space-between;gap:24px;padding:10px 0;border-bottom:1px solid #ddd}.order-ticket dt{font-weight:700}.order-ticket dd{margin:0;text-align:right}.ticket-code{display:grid;place-items:center;width:180px;height:180px;margin:0 auto 30px;background:repeating-linear-gradient(45deg,#111 0 8px,#fff 8px 16px);border:12px solid #fff;outline:2px solid #111;color:#fff;font-weight:900;text-shadow:0 1px 3px #000}.order-management{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:24px}.order-management fieldset{display:flex;flex-wrap:wrap;align-items:end;gap:10px;margin:0;padding:16px;border:1px solid #d4d4d4}.order-management legend{padding:0 6px;font-size:14px;font-weight:800}.order-management textarea{box-sizing:border-box;width:100%;min-height:72px;padding:8px 10px;resize:vertical}.order-management fieldset>label:not(.check-option){flex:1 1 180px}.order-management .check-row{display:flex;flex:1 1 100%;flex-wrap:wrap;gap:12px}.order-management .check-option{display:flex;flex-direction:row;align-items:center}.order-management .check-option input{width:auto;height:auto}.order-management>.form-message{grid-column:1/-1;min-height:22px;margin:0}@media(max-width:700px){.order-management{grid-template-columns:1fr}.order-management>.form-message{grid-column:1}}
/* Public movie-directory contract. */
.movies-page{min-height:1400px;padding:96px 0 80px;background:#000;color:#fff}.movies-page h1{margin:0 0 24px;font-size:32px;font-weight:700;line-height:48px;letter-spacing:-.96px}.movies-page-toolbar{height:45px;display:flex;align-items:flex-start;border-bottom:2px solid #a8b8bc}.featured-select{width:233.578px;height:36px;padding:0;border:0;background:transparent;color:#fff;font-size:24px;font-weight:700;line-height:36px;text-align:left}.featured-select span{display:inline-block;width:11px;height:11px;margin:0 0 6px 12px;border-right:1.5px solid #fff;border-bottom:1.5px solid #fff;transform:rotate(45deg)}.movies-page-toolbar nav{height:36px;margin-left:auto;display:flex;align-items:stretch;gap:12px}.movies-page-toolbar nav a{height:36px;padding:0;display:flex;align-items:center;font-size:16px;font-weight:500;line-height:24px;color:#a8b8bc}.movies-page-toolbar nav a.on{color:#fff;text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:8px}.movies-page-filter{position:relative;height:57px;padding-top:9px;display:flex;align-items:flex-start;gap:16px}.movies-page-filter>span{font-size:12px;font-weight:400;line-height:24px;color:#a8b8bc}.movies-page-filter label{position:relative;width:193.117px;height:24px}.filter-sliders{position:absolute;left:0;top:0;width:18px;height:24px;font-size:22px;line-height:24px;transform:rotate(90deg)}.movies-page-filter select{width:193.117px;height:24px;padding:0 18px 0 24px;border:0;background:#000;color:#fff;font-size:16px;font-weight:400;line-height:24px;appearance:none}.movies-page-filter label:after{content:'';position:absolute;right:2px;top:6px;width:8px;height:8px;border-right:1.5px solid #fff;border-bottom:1.5px solid #fff;transform:rotate(45deg);pointer-events:none}.listing-search,.listing-sort,.movies-page-filter>button{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}.movies-page-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:52px 16px}.listing-poster{display:block;width:100%;aspect-ratio:2/3;background-size:cover;background-position:center}.movie-listing-card h3{margin:8px 0 3px;font-size:20px;font-weight:900;line-height:25px;letter-spacing:-.4px}.movie-listing-card p{margin:0 0 4px;font-size:14px;font-weight:400;line-height:21px;color:#d6dfe2}.info-dot{display:inline-grid;width:12px;height:12px;place-items:center;border:1px solid #1ab7fd;border-radius:50%;color:#1ab7fd;font-size:8px}.listing-actions{display:flex;align-items:center;gap:8px;margin-top:12px}.listing-actions .button{height:48px;min-height:48px;padding:0 24px;border:0;border-radius:9999px;background:#ce0e2d;font-size:16px;font-weight:700}.listing-actions .heart{border-color:#fff;background:#000;color:#fff}.movies-empty{color:#111}
.movie-listing-card h3{margin-bottom:11px}.movie-listing-card p{color:#d6dfe2;font-size:12px;font-weight:500}.movie-listing-card p:first-of-type{margin:0 0 8px;line-height:12px}.movie-listing-card p:nth-of-type(2){margin:0;padding:0 0 8px;line-height:15px}.listing-actions{margin-top:8px}.listing-actions .button{line-height:24px}.listing-actions .heart{display:none}
.movie-listing-card h3{line-height:26.5px;margin-bottom:8px;letter-spacing:-.6px}.listing-meta{height:12.5px;margin:0 0 8px;padding:0;display:flex;flex-wrap:wrap;list-style:none;font-size:12px;font-weight:500;line-height:12px;color:#d6dfe2}.listing-meta li{height:12.5px;padding-left:4.584px;transform:translateX(-4.584px)}.listing-meta li:first-child{padding-right:4.584px;border-right:2px solid #95a8ae}.listing-runtime-info{display:flex;align-items:center;gap:4.584px}.listing-info{position:relative;display:block;width:12px;height:13px;margin-top:-.5px;color:#1ab7fd}.listing-info svg{display:block;width:12px;height:12px;fill:currentColor}.listing-info svg path:nth-child(2){display:none}.listing-info:after{content:'?';position:absolute;inset:0;display:grid;place-items:center;font-size:7px;font-weight:700;line-height:12px}.listing-release{margin:0!important;padding:0 0 8px!important;font-size:12px!important;font-weight:500!important;line-height:15px!important;color:#d6dfe2}
.movie-listing-card h3 a{position:relative;top:-1px}
@media(max-width:560px){.movies-page{padding:96px 0 60px}.movies-page>.wrap{width:calc(100% - 16px)}.movies-page h1{font-size:32px;line-height:48px;letter-spacing:normal}.movies-page-toolbar{height:86px;min-height:86px;flex-wrap:wrap}.featured-select{font-size:24px}.movies-page-toolbar nav{width:100%;height:24px;margin:9px 0 0}.movies-page-toolbar nav a{height:24px;display:block;text-decoration-thickness:2px;text-underline-offset:8px}.movies-page-filter{height:56px;padding-top:8px}.movies-page-filter>span{padding-top:8px;line-height:18px;transform:translateY(-5px)}.movies-page-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:32px 16px}.movie-listing-card h3{margin-bottom:9px;font-size:18px;line-height:23.5px;letter-spacing:-.54px}.movie-listing-card h3 a{top:-.5px}.movie-listing-card p{font-size:12px}.listing-actions .button{height:48px;min-height:48px;padding:0 24px;font-size:14px;line-height:21px}.listing-actions .heart{display:none}}
/* Public theatre-directory contract. */
.theatre-directory{min-height:1400px;padding:32px 0 80px;background:#000;color:#fff;font-family:Gordita,Helvetica,sans-serif}.theatre-directory h1{height:48px;margin:0 0 16px;font-size:32px;font-weight:700;line-height:48px;letter-spacing:normal}.directory-search{display:flex;align-items:center;gap:4px;width:100%;height:59px;padding:0 12px;border:0;border-radius:4px;background:rgba(174,205,224,.2);box-shadow:inset 0 0 0 2px #95a4a9}.directory-search input{min-width:0;height:59px;flex:1;padding:12px 8px 12px 0;border:0;outline:0;background:transparent;color:#fff;font-size:28px;font-weight:500;line-height:35px}.directory-search input::placeholder{color:#8f9699;opacity:1}.directory-search-button{position:static;flex:none;width:28px;height:28px;padding:0;border:0;background:transparent}.directory-search-button img{display:block;width:28px;height:28px}.use-location{display:flex;align-items:center;gap:8px;height:24px;margin:16px 0 0;padding:0;border:0;background:transparent;color:#1ab7fd;font-size:16px;font-weight:700;line-height:24px;cursor:pointer}.use-location span{font-size:16px;font-weight:400}.directory-index{margin-top:96px}.directory-index-heading{height:58px;border-bottom:2px solid #a8b8bc;display:flex;align-items:flex-start}.directory-index-heading h2{height:48px;margin:0;font-size:32px;font-weight:700;line-height:48px;letter-spacing:normal}.directory-index-heading>div{height:48px;margin-left:auto;display:flex;align-items:flex-start;gap:12px}.directory-index-heading button{height:48px;padding:0;border:0;background:transparent;color:#a8b8bc;font-size:16px;font-weight:500;line-height:24px}.directory-index-heading button.on{color:#fff;text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:8px}.directory-links{padding-top:20px;display:grid;grid-auto-flow:column;grid-template-columns:repeat(4,300px);grid-template-rows:repeat(39,24px);column-gap:16px;row-gap:20px}.directory-links>div{width:300px;height:24px}.directory-links a{display:inline-flex;align-items:center;gap:4px;height:24px;color:#1ab7fd;font-size:16px;font-weight:400;line-height:24px}.directory-links a:after{content:"";display:block;width:9px;height:9px;margin-left:1px;border-top:1.5px solid #1ab7fd;border-right:1.5px solid #1ab7fd;transform:rotate(45deg)}.directory-links[hidden]{display:none}.state-links{min-height:420px}
@media(max-width:560px){.theatre-directory{padding:31.5px 0 60px}.theatre-directory>.wrap{width:calc(100% - 16px)}.theatre-directory h1{height:48px;margin-bottom:16px;font-size:32px;font-weight:700;line-height:48px;letter-spacing:normal}.directory-search,.directory-search input{height:54px}.directory-search input{font-size:24px;line-height:30px;white-space:nowrap;text-overflow:clip}.directory-search-button,.directory-search-button img{width:24px;height:24px}.use-location{margin-top:16px;font-size:14px;line-height:21px}.directory-index{margin-top:93.5px}.directory-index-heading{height:46px}.directory-index-heading h2{height:36px;font-size:24px;font-weight:700;line-height:36px;letter-spacing:normal}.directory-index-heading>div{height:36px;gap:12px}.directory-index-heading button{height:36px;padding:0;font-size:16px;line-height:24px}.directory-links{padding-top:20px;grid-template-columns:repeat(2,179px);grid-template-rows:repeat(78,24px);column-gap:16px;row-gap:20px}.directory-links>div{width:179px;height:24px}.directory-links a{height:24px;font-size:16px;line-height:24px;white-space:nowrap}.directory-links a:after{display:none}}
@media(max-width:560px){.theatre-directory{padding-top:31.5px}}
/* Public theatre showtimes surface. */
.showtimes-shell{margin:0;background:#000;color:#fff;font-family:Gordita,Helvetica,sans-serif}.showtimes-page{min-height:1200px;background:#000}.showtimes-top{position:relative;height:59px;border-bottom:1px solid #182025;background:#080b0d;display:flex;align-items:center;justify-content:center}.showtimes-top h1{margin:0;font-size:20px;font-weight:700;line-height:30px}.showtimes-top>a{position:absolute;top:13px;width:32px;height:32px;display:grid;place-items:center;font-size:39px;font-weight:300;line-height:26px}.showtimes-top>a:first-child{left:105px}.showtimes-top>a:last-child{right:105px;font-size:38px}.showtimes-filters{height:58px;border-bottom:1px solid #182025;background:#080b0d;display:flex;justify-content:center}.showtimes-filters a{height:58px;padding:0 18px;border-left:1px solid #182025;display:flex;align-items:center;gap:10px;font-size:18px;font-weight:400;line-height:27px}.showtimes-filters a:last-child{border-right:1px solid #182025}.showtimes-filters span{font-size:20px}.showtimes-filters strong{font-weight:400}.showtimes-filters b{font-size:18px;font-weight:400}.showtimes-content{width:1248px;margin:0 auto;display:grid;grid-template-columns:716px 476px;gap:56px}.showtimes-list{padding-top:23px}.showtimes-note{height:43px;margin:0;display:flex;align-items:flex-start;gap:9px;font-size:14px;font-weight:700;line-height:21px}.showtimes-note span{font-size:18px}.showtimes-movie{position:relative;height:230px;padding:42px 0 0;border-bottom:7px solid #40545b}.showtimes-movie>img{position:absolute;left:0;top:42px;width:90px;height:90px;border-radius:50%;object-fit:cover}.showtimes-copy{margin-left:106px}.showtimes-copy h2{margin:0 0 2px;font-size:26px;font-weight:700;line-height:32px}.showtimes-copy p,.showtimes-feature p{margin:0;font-size:16px;line-height:24px}.showtime-info{display:inline-grid;width:15px;height:15px;place-items:center;border:1px solid #1ab7fd;border-radius:50%;color:#1ab7fd;font-size:9px;line-height:14px}.showtimes-empty{position:absolute;left:0;bottom:38px;display:flex;align-items:center;gap:16px;font-size:15px;line-height:22px}.showtimes-empty>span{color:#68828a}.showtimes-empty a{color:#1ab7fd}.showtimes-empty b{font-size:29px;font-weight:300;vertical-align:-2px}.showtimes-feature{padding-top:50px}.showtimes-video{height:201px;background:linear-gradient(#0019,#0019),url('/local-assets/hero-insidious-mobile.jpg') center 36%/cover;display:grid;place-items:center}.showtimes-video span{width:61px;height:61px;border:2px solid #fff;border-radius:50%;display:grid;place-items:center;font-size:32px}.showtimes-feature h2{margin:76px 0 2px;font-size:27px;font-weight:700;line-height:34px}.showtimes-feature>a{height:55px;margin-top:13px;border-top:1px solid #a8b8bc;display:flex;align-items:center;gap:10px;font-size:18px}.showtimes-feature>a span{width:40px;height:40px;border:2px solid #fff;border-radius:50%;display:grid;place-items:center}.showtimes-feature>a b{margin-left:2px;font-size:30px;font-weight:300}
@media(max-width:560px){.showtimes-page{min-height:1400px}.showtimes-top{height:56px}.showtimes-top h1{font-size:16px;line-height:24px}.showtimes-top>a{top:12px;width:32px;height:32px;font-size:34px}.showtimes-top>a:first-child{left:10px}.showtimes-top>a:last-child{right:10px}.showtimes-filters{height:88px}.showtimes-filters a{width:25%;height:88px;padding:5px 3px;border-left:1px solid #182025;display:flex;flex-direction:column;justify-content:center;gap:1px;text-align:center;font-size:14px;line-height:18px}.showtimes-filters a:first-child{border-left:0}.showtimes-filters span{height:24px;font-size:19px}.showtimes-filters strong{min-height:36px;display:grid;place-items:center}.showtimes-filters b{height:15px;font-size:16px;line-height:12px}.showtimes-content{width:100%;margin:0;display:block}.showtimes-list{padding:20px 16px 0}.showtimes-note{height:59px;font-size:14px;line-height:21px}.showtimes-movie{height:230px;padding-top:20px}.showtimes-movie>img{top:20px;width:90px;height:90px}.showtimes-copy{margin-left:106px;min-height:103px;display:flex;flex-direction:column;justify-content:center}.showtimes-copy h2{font-size:20px;line-height:26px}.showtimes-copy p{font-size:16px;line-height:24px}.showtimes-empty{bottom:39px;gap:16px;font-size:15px;white-space:nowrap}.showtimes-feature{display:none}}
.showtimes-note{height:20px}
@media(max-width:560px){.showtimes-note{height:36px}.showtimes-copy{min-height:90px}.showtimes-copy h2{font-size:18px;line-height:27px}}
@media(max-width:560px){.showtimes-movie{border-bottom:0}.showtimes-movie:after{content:"";position:absolute;left:0;right:0;bottom:29px;height:7px;background:#40545b}.showtimes-empty{bottom:68px}}
.showtimes-video{background-image:linear-gradient(#0019,#0019),url('/local-assets/showtime-video.jpg');background-position:center;background-size:cover}.showtimes-copy h2{text-wrap:balance}.showtimes-note{padding-left:9px;gap:10px;font-weight:500;line-height:17.5px}.showtimes-note span{width:18px}.showtimes-empty{font-size:14px;line-height:21px}.showtimes-empty>span{color:#5b7178}.showtimes-empty b{width:18px;height:18px;font-size:0;background:url('/local-icons/chevron-blue.svg') center/18px 18px no-repeat}.showtimes-empty a{display:flex;align-items:center;gap:4px}
@media(max-width:560px){.showtimes-empty{bottom:76px}}
.showtimes-top>a svg{width:20px;height:20px}.showtimes-top>a:last-child svg{width:22px;height:22px}
.showtimes-filters span svg{width:20px;height:20px;display:block}.showtimes-filters b svg{width:12px;height:12px;display:block}.showtimes-note span svg{width:20px;height:20px;display:block}
@media(max-width:560px){.showtimes-top>a svg{width:18px;height:18px}.showtimes-top>a:last-child svg{width:20px;height:20px}.showtimes-filters span svg{width:18px;height:18px}.showtimes-filters b svg{width:12px;height:12px}}
@media(max-width:560px){
  .showtimes-top,.showtimes-filters{background:#0a0b0c;border-color:#1c2023}
  .showtimes-top>a svg{width:20px;height:20px}
  .showtimes-top h1{transform:translateY(.5px) scaleX(.953);transform-origin:center}
  .showtimes-filters a{border-color:#1c2023}
  .showtimes-filters span svg{transform:translateY(1.5px)}
  .showtimes-filters strong{font-size:12px;line-height:18px;transform:translateY(-2px)}
  .showtimes-filters a:nth-child(4)>span svg{transform:translate(.5px,1.5px)}
  .showtimes-filters b svg{transform:translateY(1.5px)}
}
@media(min-width:561px){
  .showtimes-mobile-break{display:none}
  .showtimes-top,.showtimes-filters{background:#0a0b0c;border-color:#1c2023}
  .showtimes-top>a{top:13.5px}
  .showtimes-top h1{font-size:18px;line-height:27px;transform:translateY(1px)}
  .showtimes-top>a:first-child{left:106px}
  .showtimes-top>a:last-child svg{width:20px;height:20px}
  .showtimes-filters a{box-sizing:border-box;padding:0;justify-content:flex-start;gap:8px;font-size:16px;line-height:24px;border-color:#1c2023}
  .showtimes-filters a:nth-child(1){width:226px}
  .showtimes-filters a:nth-child(2){width:127px}
  .showtimes-filters a:nth-child(3){width:162px}
  .showtimes-filters a:nth-child(4){width:239px}
  .showtimes-filters a:nth-child(1){padding-left:26.3046875px}
  .showtimes-filters a:nth-child(2){padding-left:16.5703125px}
  .showtimes-filters a:nth-child(3){padding-left:16.796875px}
  .showtimes-filters a:nth-child(4){padding-left:16.7734375px}
  .showtimes-filters span svg{width:18px;height:18px}
  .showtimes-list{padding-top:12px}
  .showtimes-note{box-sizing:border-box;height:44px;padding:0;align-items:center;justify-content:center;gap:8px}
  .showtimes-movie{height:230px;padding-top:42px;border-bottom:0}
  .showtimes-movie:after{content:"";position:absolute;left:0;right:0;bottom:21px;height:7px;background:#40545b}
  .showtimes-movie>img{top:28px}
  .showtimes-copy h2{font-size:24px;line-height:36px}
  .showtimes-empty{bottom:68px}
  .showtimes-feature{padding-top:16px}
  .showtimes-video{height:268px;background-image:url('/local-assets/showtime-video.jpg');background-position:top center;background-size:476px 268px}
  .showtimes-feature h2{margin:39px 0 2px;font-size:24px;line-height:36px;font-weight:500}
  .showtimes-feature p{font-size:14px;line-height:21px}
  .showtimes-feature>a{box-sizing:border-box;height:40px;margin-top:19px;font-size:16px;line-height:24px}
}
/* Public AMC Stubs tier selection; account creation continues after a plan choice. */
.stubs-shell{margin:0;background:#000;color:#fff;font-family:Gordita,Helvetica,sans-serif}.stubs-shell main{min-height:1100px;background:#000}.stubs-top{box-sizing:border-box;height:60px;border-bottom:1px solid #1c2023;background:#0a0b0c;position:relative;display:flex;align-items:center;justify-content:center}.stubs-top h1{margin:0;font-size:18px;line-height:27px;font-weight:700}.stubs-top a{position:absolute;right:106px;top:19px;width:20px;height:20px;color:#fff}.stubs-top svg{display:block;width:20px;height:20px}.stubs-test-hook{display:none}.stubs-tiers{width:1248px;margin:65px auto 0;display:grid;grid-template-columns:repeat(3,1fr);gap:16px;align-items:start}.stubs-tier{box-sizing:border-box;min-height:215px;border-radius:16px;padding:24px;color:#090b0c;background-size:cover;background-position:center}.stubs-tier.insider{min-height:241px;background-image:url('/local-assets/stubs-bg-insider.jpg')}.stubs-tier.premiere{background-image:url('/local-assets/stubs-bg-premiere.jpg')}.stubs-tier.alist{min-height:241px;color:#fff;background-image:url('/local-assets/stubs-bg-alist.jpg')}.stubs-tier-head{height:44px;display:flex;align-items:center;justify-content:space-between}.stubs-tier-head>a{box-sizing:border-box;min-width:117px;height:44px;border:2px solid #081015;border-radius:24px;display:grid;place-items:center;color:#071015;font-size:14px;font-weight:700}.stubs-tier.premiere .stubs-tier-head>a{border:0;background:#ec1532;color:#fff}.stubs-tier.alist .stubs-tier-head>a{border:0;background:#fff;color:#080b0c}.stubs-wordmark{height:35px;width:auto;object-fit:contain}.stubs-tier h2{margin:15px 0 8px;font-size:18px;line-height:27px;font-weight:700}.stubs-tier p{margin:0;font-size:17px;line-height:26px}.stubs-register{margin:95px auto 0;text-align:center;font-size:16px;line-height:24px}.stubs-register>span{display:inline-grid;width:14px;height:14px;border:1px solid #00bdf7;border-radius:50%;place-items:center;color:#00bdf7;font-size:9px}.stubs-register a{color:#00bdf7}.stubs-compare{width:1248px;margin:100px auto 0}.stubs-compare>h2{margin:0 0 21px;text-align:center;font-size:38px;line-height:48px}.stubs-table{display:grid;grid-template-columns:repeat(5,1fr);border-radius:15px 15px 0 0;overflow:hidden;gap:4px;background:#000}.stubs-table>div{min-height:74px;background:#4d1d52;display:grid;place-items:center;text-align:center;color:#18baf3;font-size:26px;line-height:26px;font-weight:700}.stubs-table>div:first-child,.stubs-table>div:nth-child(6){background:#292840;color:#fff}.stubs-table>div:nth-child(n+6){min-height:84px;background:#251129;font-size:38px}.stubs-table small{font-size:17px;line-height:18px}
@media(max-width:560px){.stubs-shell main{min-height:1500px}.stubs-top{height:57px}.stubs-top h1{font-size:16px;line-height:24px}.stubs-top a{right:16px;top:18px;width:20px;height:20px}.stubs-tiers{width:auto;margin:65px 16px 0;display:block}.stubs-tier{min-height:0;margin-bottom:16px;padding:24px;border-radius:16px}.stubs-tier.insider{min-height:264px}.stubs-tier.premiere{min-height:211px}.stubs-tier.alist{min-height:264px}.stubs-tier-head{height:44px}.stubs-tier-head>a{min-width:117px;height:44px;font-size:14px}.stubs-wordmark{gap:4px}.stubs-wordmark em{font-size:28px}.stubs-wordmark span{font-size:18px}.stubs-tier h2{margin:16px 0 8px;font-size:16px;line-height:24px}.stubs-tier p{font-size:16px;line-height:26.4px}.stubs-register{margin:72px 25px 0;font-size:15px}.stubs-compare{width:auto;margin:80px 16px 0}.stubs-compare>h2{font-size:28px;line-height:36px}.stubs-table{min-width:850px}.stubs-compare{overflow:hidden}}
.stubs-tier{padding-bottom:16px}.stubs-tier h2{margin-top:16px}.stubs-tier p{font-size:16px;line-height:26.4px}.stubs-learn{color:#00bdf7}.stubs-table>div:nth-child(6),.stubs-table>div:nth-child(11){font-size:14px;line-height:18px;color:#fff}.stubs-table>div:nth-child(n+11){min-height:84px;background:#4d1d52;font-size:18px;line-height:21px}.stubs-table>div:nth-child(11){background:#292840;font-size:14px;line-height:18px}
@media(max-width:560px){.stubs-tier-head{height:44px}.stubs-tier h2{font-size:16px;line-height:24px}}
.stubs-tier{background-position:0 0;background-repeat:no-repeat}.stubs-premiere-break{display:none}.stubs-compare>h2{font-size:36px;line-height:54px;transform:translateY(-5px) scaleX(.95)}.stubs-compare>h2{margin-bottom:12.6px}.stubs-table>div{min-height:76.8px;background:#431c4a;font-size:24px;line-height:26.4px}.stubs-table>div:first-child{background:#292840}.stubs-table>div:nth-child(n+6){min-height:83.4px;background:#26112a}.stubs-table>div:nth-child(6){font-size:16px;line-height:17.6px;background:#171622}.stubs-table>div:nth-child(n+11){min-height:80.2px;background:#431c4a;font-size:18px;line-height:19.8px}.stubs-table>div:nth-child(11){font-size:16px;line-height:17.6px;background:#292840}
@media(max-width:560px){.stubs-top h1{transform:scaleX(.9473)}.stubs-tier.premiere .stubs-tier-head>a{min-width:108.75px;width:108.75px;line-height:17px}.stubs-tier.premiere .stubs-premiere-break{display:block}}
.stubs-table>div.stubs-key{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px}.stubs-table>div.stubs-key small{font-size:12px;line-height:15px;font-weight:400}.stubs-table>div.stubs-points-cell{display:flex;flex-direction:column;align-items:center;justify-content:center}.stubs-points-cell>span{font-size:36px;line-height:39.6px}.stubs-table .stubs-points-cell>small{font-size:18px;line-height:19.8px}
.stubs-table>div:nth-child(5n+2){color:rgb(26,183,253)}.stubs-table>div:nth-child(5n+3){color:rgb(91,172,153)}.stubs-table>div:nth-child(5n+4){color:rgb(251,173,24)}.stubs-table>div:nth-child(5n+5){color:rgb(193,54,56)}
.stubs-key-title{display:block;transform:translateY(-1px) scaleX(.935)}.stubs-table>div.stubs-key small{transform:translateY(1px) scaleX(.915)}
/* Public help center surface with retained local FAQ behavior. */
.help-hero{height:450px;background-image:radial-gradient(rgba(0,0,0,0) 50%,#000 100%),linear-gradient(45deg,#000,rgba(0,0,0,0) 50%),url('/local-assets/help-hero.avif');background-size:cover;background-position:100% 50%;position:relative}.help-hero>.wrap{height:100%;display:flex;align-items:flex-end}.help-hero h1{margin:0 0 73px;font-size:38px;line-height:48px;font-weight:700;color:#fff}.help-actions{padding-top:34px;padding-bottom:40px;color:#fff}.help-actions>p{margin:0 0 18px;font-size:16px;line-height:24px}.help-actions nav{display:flex;align-items:center;gap:20px;flex-wrap:wrap}.help-actions nav a{box-sizing:border-box;height:48px;padding:0 22px;border:2px solid #fff;border-radius:26px;display:grid;place-items:center;font-size:16px;line-height:24px;font-weight:700;color:#fff}.help-search{box-sizing:border-box;height:60px;margin-top:80px;background:#161b1f;position:relative}.help-search label{position:absolute;left:12px;top:10px;font-size:29px;line-height:40px;font-weight:700;color:#7f8182}.help-search input{box-sizing:border-box;width:100%;height:60px;padding:0 62px 0 12px;border:0;background:transparent;color:#fff;font-size:24px}.help-search:after{content:"";position:absolute;right:17px;top:15px;width:24px;height:24px;border:1px solid #a9bbc2;border-radius:50%}.help-topics{display:grid;grid-template-columns:200px 1fr;gap:40px;padding-top:0;color:#fff}.help-topics h2{font-size:22px;line-height:30px}.help-topics details{border-bottom:1px solid #555;padding:18px 0}.help-topics summary{font-size:20px;font-weight:700}.help-topics p{font-size:16px;line-height:24px}
.help-actions,.help-topics{background:#000;box-shadow:0 0 0 100vmax #000;clip-path:inset(0 -100vmax)}.help-actions{padding-top:32px;padding-bottom:18px}.help-actions>p{margin-bottom:16px;line-height:26.4px}.help-actions nav a{line-height:26.4px}
@media(max-width:560px){.help-hero{height:410px;background-image:radial-gradient(rgba(0,0,0,0) 50%,#000 100%),linear-gradient(45deg,#000,rgba(0,0,0,0) 50%),url('/local-assets/help-hero-mobile.avif');background-position:50% 50%}.help-hero>.wrap{box-sizing:border-box;padding:0 4px}.help-hero h1{margin:0 0 34.4px;font-size:28px;line-height:35px;font-weight:900}.help-actions{box-sizing:border-box;width:auto;margin-left:0;margin-right:0;padding:32px 8px 35px}.help-actions>p{margin:0 0 16px;font-size:16px;line-height:26.4px;max-width:374px}.help-actions nav{display:flex;flex-direction:column;align-items:flex-start;gap:0}.help-actions nav a{height:48px;margin:0 0 0;padding:0 22px;font-size:14px;line-height:23.1px}.help-actions nav a:nth-child(n+2){margin-left:8px}.help-search{margin-top:50px}.help-search label{font-size:22px}.help-topics{display:block;padding:0 12px 60px}.help-topics aside{display:none}.help-topics h2{font-size:24px}.help-topics summary{font-size:20px;line-height:28px}.help-topics p{font-size:16px;line-height:26px}}
.help-actions{padding-bottom:12.75px}.help-search label{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}.help-search input{width:1192px;height:59px;margin-left:12px;padding:12px 8px 12px 0;font-size:28px;line-height:35px;font-weight:500}.help-search input::placeholder{color:#7f8182;opacity:1}.help-topics aside h2{font-size:20px;line-height:30px}.help-topics>div>h2{font-size:24px;line-height:36px}
/* Public theatre detail surface; ticketing and local theatre actions remain functional. */
.theatre-source-hero{box-sizing:border-box;height:450px;color:#fff;background-image:radial-gradient(rgba(0,0,0,0) 50%,#000 100%),linear-gradient(45deg,#000,rgba(0,0,0,0) 50%),url('/local-assets/theatre-hero-desktop.avif');background-position:100% 50%;background-size:cover}.theatre-source-hero>.wrap{box-sizing:border-box;height:100%;padding-top:166px}.theatre-source-features{width:900px;margin:0 0 8px;font-size:14px;line-height:22px}.theatre-source-hero h1{margin:0 0 12px;font-size:62px;line-height:69px;font-weight:900;letter-spacing:-2px}.theatre-source-address{margin:0 0 27px;font-size:22px;line-height:29px}.theatre-source-actions{display:flex;align-items:center;gap:16px}.theatre-source-actions>a,.theatre-source-actions>button{box-sizing:border-box;height:48px;border:0;background:transparent;color:#fff;display:flex;align-items:center;justify-content:center;font-size:18px;line-height:27px;font-weight:700;white-space:nowrap}.theatre-source-actions>.theatre-primary{padding:0 24px;border-radius:28px;background:#e5092f}.theatre-source-actions>.food{padding:0 25px}.theatre-source-actions>button span,.theatre-source-actions>.nearby span{width:44px;height:44px;margin-right:8px;border:2px solid #fff;border-radius:50%;display:grid;place-items:center;font-size:29px;line-height:44px;font-weight:400}.theatre-source-actions>.nearby span{font-size:24px}.theatre-source-movies{box-sizing:border-box;min-height:720px;padding-top:31px;color:#fff;background:#000;position:relative}.theatre-source-movies:before{content:"";position:absolute;inset:0;background:url('/local-assets/theatre-bg.avif') center top/cover no-repeat;opacity:.5}.theatre-source-movies>.wrap{position:relative}.theatre-source-movies-head{height:88px;border-bottom:2px solid #a9b9bc;display:flex;align-items:flex-start;justify-content:space-between}.theatre-source-movies-head h2{margin:0;font-size:38px;line-height:48px;font-weight:900;letter-spacing:-1px}.theatre-source-movies-head label{display:flex;align-items:center;gap:10px;font-size:18px;line-height:27px}.theatre-source-movies-head select{box-sizing:border-box;width:199px;height:48px;padding:0 40px 0 12px;border:0;border-radius:3px;background:#7d898d;color:#fff;font:700 16px/24px Gordita,Helvetica,sans-serif}.theatre-preview-rail{width:calc(100vw + 160px);margin-left:-160px;padding-top:64px;display:grid;grid-template-columns:repeat(5,278px);gap:76px;overflow:hidden}.theatre-preview{min-width:0}.theatre-preview img{display:block;width:278px;height:410px;object-fit:cover;filter:grayscale(.12);opacity:.76}.theatre-preview h3{font-size:20px}.theatre-preview .showtime{margin-right:5px}
@media(max-width:560px){.theatre-source-hero{height:410px;background-image:linear-gradient(90deg,rgba(0,0,0,.79) 0,rgba(0,0,0,.2) 88%),linear-gradient(0deg,rgba(0,0,0,.35),transparent 45%),url('/local-assets/theatre-hero-mobile.avif');background-position:center top}.theatre-source-hero>.wrap{padding:8px 16px 0}.theatre-source-features{width:auto;margin:0 0 7px;font-size:14px;line-height:23px}.theatre-source-hero h1{margin:0 0 8px;font-size:40px;line-height:48px;letter-spacing:-1.4px}.theatre-source-address{width:355px;margin:0 0 24px;font-size:20px;line-height:30px}.theatre-source-actions{display:grid;grid-template-columns:131px 195px;grid-auto-rows:48px;column-gap:16px;row-gap:31px}.theatre-source-actions>.theatre-primary{padding:0;font-size:14px;line-height:21px}.theatre-source-actions>.food{padding:0}.theatre-source-actions>button,.theatre-source-actions>.nearby{justify-content:flex-start;font-size:16px;line-height:24px}.theatre-source-actions>button span,.theatre-source-actions>.nearby span{width:34px;height:34px;margin-right:6px;font-size:23px;line-height:34px}.theatre-source-movies{min-height:900px;padding-top:31px}.theatre-source-movies>.wrap{padding:0 16px}.theatre-source-movies-head{height:89px;display:block}.theatre-source-movies-head h2{margin:0 0 7px;font-size:30px;line-height:38px;letter-spacing:-.7px}.theatre-source-movies-head label{gap:8px;font-size:16px;line-height:24px}.theatre-source-movies-head select{width:198px;height:48px;font-size:16px}.theatre-preview-rail{width:auto;margin:0;padding:67px 26px 0;display:block;overflow:hidden}.theatre-preview{width:306px}.theatre-preview:nth-child(n+2){display:none}.theatre-preview img{width:306px;height:452px;opacity:.72}.theatre-preview h3{font-size:18px}}
@media(max-width:560px){.theatre-source-hero{background-image:radial-gradient(rgba(0,0,0,0) 50%,#000 100%),linear-gradient(45deg,#000,rgba(0,0,0,0) 50%),url('/local-assets/theatre-hero-mobile.avif')}}
.theatre-source-features{width:936px;height:38px;margin-bottom:8px;font-size:12px;line-height:15px}.theatre-source-hero h1{margin-bottom:11px;font-size:56px;line-height:70px}.theatre-source-address{margin-bottom:27px;font-size:20px;line-height:33px}.theatre-source-actions>.theatre-primary{padding:0 24px;font-size:16px;line-height:24px}.theatre-source-actions>.food{padding:0 24px}.theatre-source-actions>button{padding:0}.theatre-preview-rail{position:relative;width:100vw;height:520px;margin-left:calc((1248px - 100vw)/2);padding:64px 0 0;display:block;overflow:hidden}.theatre-preview{position:absolute;top:64px;width:278px}.theatre-preview:nth-child(1){left:-155px}.theatre-preview:nth-child(2){left:213px}.theatre-preview:nth-child(3){left:567px;width:306px;top:36px}.theatre-preview:nth-child(4){left:949px}.theatre-preview:nth-child(5){left:1317px}.theatre-preview img{width:278px;height:417px;opacity:.6;filter:none}.theatre-preview:nth-child(3) img{width:306px;height:459px}
@media(max-width:560px){.theatre-source-hero>.wrap{box-sizing:border-box;width:100%;margin:0;padding:8px 16px 0}.theatre-source-features{width:358px;height:115px;margin-bottom:7px;font-size:14px;line-height:23px}.theatre-source-hero h1{margin-bottom:8px;font-size:40px;line-height:48px}.theatre-source-address{margin-bottom:24px;font-size:20px;line-height:30px}.theatre-source-actions>.theatre-primary{padding:0;font-size:14px;line-height:21px}.theatre-source-movies>.wrap{box-sizing:border-box;width:100%;margin:0;padding:0 16px}.theatre-preview-rail{width:100%;height:570px;margin:0;padding:0;overflow:hidden}.theatre-preview{display:none}.theatre-preview:nth-child(3){display:block;left:26px;top:67px;width:306px}.theatre-preview:nth-child(3) img{width:306px;height:459px;opacity:.6}}
.theatre-source-hero>.wrap{padding-top:165px}.theatre-source-features{box-sizing:border-box;padding:0;list-style:none;display:flex;flex-wrap:wrap;align-content:flex-start;row-gap:8px}.theatre-source-features li{white-space:nowrap}.theatre-source-features li:not(:last-child):after{content:" •"}.theatre-source-address{height:27px}
@media(max-width:560px){.theatre-source-hero>.wrap{padding-top:9.5px}.theatre-source-features{height:107px;margin-bottom:8px;font-size:12px;line-height:15px;row-gap:8px}.theatre-source-hero h1{margin-bottom:10.5px;font-size:36px;line-height:45px}.theatre-source-address{width:358px;height:59.4px;margin-bottom:21.5px;font-size:18px;line-height:29.7px}.theatre-source-actions{grid-template-columns:max-content max-content;grid-auto-rows:auto;column-gap:16px;row-gap:32px}.theatre-source-actions>button,.theatre-source-actions>.nearby{height:37.1px;font-size:14px;line-height:21px}.theatre-source-actions>button span,.theatre-source-actions>.nearby span{width:37.1px;height:37.1px;margin-right:8px;font-size:23px;line-height:37px}}
.theatre-source-features li:not(:last-child){margin-right:4.6484375px}.theatre-source-actions>button,.theatre-source-actions>.nearby{gap:8px}.theatre-source-actions svg{width:2.65em;height:100%;flex:0 0 auto}.theatre-source-actions>button>span,.theatre-source-actions>.nearby>span{width:auto;height:auto;margin:0;border:0;border-radius:0;display:inline;font:inherit;line-height:inherit}
@media(max-width:560px){.theatre-source-actions{position:relative;display:block;height:117.1px}.theatre-source-actions>.theatre-primary,.theatre-source-actions>button,.theatre-source-actions>.nearby{position:absolute}.theatre-source-actions>.theatre-primary:first-child{left:0;top:0;width:131.0390625px}.theatre-source-actions>.food{left:147.0390625px;top:0;width:194.609375px}.theatre-source-actions>button{left:0;top:80px;width:138.53125px}.theatre-source-actions>.nearby{left:154.53125px;top:80px;width:164.96875px}.theatre-source-movies-head h2{margin:0;font-size:28px;line-height:35px;letter-spacing:-.84px}.theatre-source-movies-head label{gap:16px}.theatre-source-movies-head select{width:174.5px;height:44px;padding:12px 24px 12px 0;font-weight:500;line-height:20px}.theatre-preview:nth-child(3){top:69px}}
.theatre-source-hero h1{letter-spacing:-1.68px}.theatre-source-address{transform:translateY(-2.484375px)}
@media(max-width:560px){.theatre-source-hero h1{letter-spacing:-1.08px}}
@media(max-width:560px){
  .account>span{display:block!important;width:4px;max-width:4px;overflow:hidden}
  .help-search input{width:100%;max-width:100%;margin-left:0}
  .directory-links{grid-template-columns:repeat(2,minmax(0,1fr))}
  .directory-links>div{width:100%;min-width:0;overflow:hidden}
  .directory-links a{max-width:100%;min-width:0;overflow:hidden;text-overflow:ellipsis}
}
.movies-page-toolbar{position:relative}.featured-select[aria-expanded="true"] span{transform:rotate(225deg) translate(-3px,-3px)}.featured-menu{position:absolute;z-index:20;top:39px;left:0;width:233px;padding:8px;background:#171d21;border:1px solid #53636a;box-shadow:0 10px 24px #0008}.featured-menu[hidden]{display:none!important}.featured-menu a{display:block;padding:10px 12px;color:#fff;font-size:14px}.featured-menu a:hover,.featured-menu a:focus{background:#253138}
.carousel-controls .dot{border:0;background:#8c8c8c}.carousel-controls .dot.on{background:#fff}
.hero-description{display:flex;flex-direction:column;gap:4px;height:auto}.hero-description small{display:block;font-size:12px;line-height:18px;color:#fff}.hero-actions{align-items:center;gap:22px}.hero-learn{color:#fff;font-size:16px;font-weight:700;text-decoration:underline;text-underline-offset:4px}
.theatre-picker-shell .showtimes-page{min-height:900px;position:relative;background:#020405}.theatre-picker{box-sizing:border-box;position:absolute;left:50%;top:45px;transform:translateX(-50%);width:660px;height:810px;border:2px solid #1ab7fd;background:#080b0d;color:#fff;box-shadow:0 24px 80px #000}.theatre-picker>header{box-sizing:border-box;height:62px;border-bottom:1px solid #3c494e;display:flex;align-items:center;justify-content:center;position:relative}.theatre-picker>header h1{margin:0;font-size:20px;line-height:30px}.theatre-picker>header a{position:absolute;top:15px;width:30px;height:30px;display:grid;place-items:center}.theatre-picker>header a:first-child{left:22px}.theatre-picker>header a:last-child{right:22px}.theatre-picker>header svg{width:22px;height:22px}.theatre-picker-body{padding:43px 48px}.theatre-picker-body h2{margin:0 0 7px;font-size:34px;line-height:44px}.theatre-picker-body>p{margin:0 0 32px;color:#a8b8bc;font-size:17px;line-height:26px}.theatre-picker-body form{height:52px;border:1px solid #a8b8bc;background:#fff;display:flex}.theatre-picker-body form input{flex:1;min-width:0;border:0;padding:0 16px;color:#111;font-size:16px}.theatre-picker-body form button{width:54px;border:0;background:#fff;padding:15px}.theatre-picker-body form img{width:22px;height:22px;filter:invert(1)}.picker-location,.picker-theatre{box-sizing:border-box;height:78px;border-bottom:1px solid #45545a;display:flex;align-items:center;color:#fff}.picker-location>span{width:42px;height:42px;border:2px solid #fff;border-radius:50%;display:grid;place-items:center;margin-right:14px;font-size:24px}.picker-location strong{font-size:17px}.picker-location>b,.picker-theatre>b{margin-left:auto;color:#1ab7fd;font-size:30px;font-weight:300}.picker-divider{height:76px;display:flex;align-items:flex-end;border-bottom:1px solid #45545a;padding-bottom:11px;color:#a8b8bc;text-transform:uppercase;font-size:12px;letter-spacing:1px}.picker-theatre>span{display:flex;flex-direction:column;gap:3px}.picker-theatre strong{font-size:18px}.picker-theatre small{color:#a8b8bc;font-size:14px}.picker-all{display:inline-flex;margin-top:35px;color:#1ab7fd;font-weight:700}
@media(max-width:560px){.hero{background-image:radial-gradient(transparent 50%,#000 100%),linear-gradient(45deg,#000,transparent 50%),url('/local-assets/hero-stubs-mobile.jpg');background-position:right center}.hero-grid{height:313px}.hero-description{height:auto;gap:4px}.hero-description small{max-width:350px;font-size:11px;line-height:16px}.hero-actions{gap:18px;margin-bottom:32px}.hero-learn{font-size:14px}.theatre-picker-shell .showtimes-page{min-height:844px}.theatre-picker{top:18px;width:calc(100% - 4px);height:808px}.theatre-picker>header{height:57px}.theatre-picker>header h1{font-size:16px}.theatre-picker>header a:first-child{left:10px}.theatre-picker>header a:last-child{right:10px}.theatre-picker-body{padding:38px 22px}.theatre-picker-body h2{font-size:28px;line-height:36px}.theatre-picker-body>p{margin-bottom:28px;font-size:16px;line-height:24px}.theatre-picker-body form{height:50px}.picker-location,.picker-theatre{height:76px}.picker-divider{height:70px}.picker-all{margin-top:28px}}
.picker-backdrop-copy{position:absolute;left:75px;top:145px;width:260px;color:#fff}.picker-backdrop-copy h2{margin:0 0 8px;font-size:30px}.picker-backdrop-copy p{color:#a8b8bc;line-height:25px}.theatre-picker>header{justify-content:flex-start;padding:0 30px}.theatre-picker>header a{left:auto!important;right:22px}.theatre-picker-body{padding:46px 48px}.theatre-picker-body>p{margin:0 0 31px;color:#a8b8bc;font-size:17px;line-height:26px}.theatre-picker-body form{border-color:#53636a;background:#171d21}.theatre-picker-body form input,.theatre-picker-body form button{background:#171d21;color:#fff}.theatre-picker-body form img{filter:none}.picker-location{margin-top:14px}
@media(max-width:560px){.picker-backdrop-copy{display:none}.theatre-picker>header{padding:0 22px}.theatre-picker>header a{right:10px}.theatre-picker-body{padding:40px 22px}.theatre-picker-body>p{margin-bottom:28px;font-size:16px;line-height:24px}}
.theatre-picker-shell>.showtimes-page>.showtimes-top{height:61px}.picker-backdrop-copy{left:96px;top:61px;width:1248px;height:136px;padding-top:28px}.theatre-picker{z-index:50;top:49px;width:652px;height:802px;border:1px solid rgb(27,32,35);background:#000;box-shadow:none}.theatre-picker>header{box-sizing:border-box;width:650px;height:73px;padding:0 32px;border-bottom:1px solid rgb(27,32,35);background:#000;justify-content:flex-start}.theatre-picker>header h1{margin:0;font-size:20px;font-weight:900;line-height:25px}.theatre-picker>header a{top:16px;right:32px;width:40px;height:40px}.theatre-picker>header svg{width:24px;height:24px}.theatre-picker-body{box-sizing:border-box;width:650px;height:236px;padding:16px 32px;background:#000}.theatre-picker-body>p{width:586px;height:24px;margin:0 0 16px;color:#fff;font-size:16px;line-height:24px}.theatre-picker-body form{box-sizing:border-box;width:586px;height:60px;padding:8px 0;border:0;background:#000}.picker-input-box{box-sizing:border-box;width:586px;height:44px;display:flex;background:rgba(174,205,224,.15)}.theatre-picker-body form input{box-sizing:border-box;width:542px;height:44px;margin-left:12px;padding:0;border:0;background:transparent;color:#fff;font-size:16px}.theatre-picker-body form button{box-sizing:border-box;width:32px;height:44px;padding:10px 0;border:0;background:transparent}.theatre-picker-body form button img{width:24px;height:24px;filter:none}.picker-location{box-sizing:border-box;width:max-content;height:24px;margin-top:16px;border:0;display:block;color:#1ab7fd;font-size:16px;font-weight:700;line-height:24px}
.theatre-picker>header a:last-child{right:32px}.theatre-picker>header h1{transform:scaleX(.949216);transform-origin:left center}.picker-location{display:flex;align-items:center;gap:8px}.picker-location:before{content:"◎";display:block;width:15px;font-size:16px;font-weight:400;line-height:24px}@media(max-width:560px){.theatre-picker>header h1{transform:scaleX(.943567)}.picker-location:before{width:14px;font-size:14px;line-height:21px}}
.picker-backdrop-copy{top:81px;height:84px;padding:0}.picker-backdrop-copy>p{height:21px;margin:0 0 15px;color:#a8b8bc;font-size:14px;line-height:21px}.picker-backdrop-copy>a{box-sizing:border-box;width:182px;height:48px;border:2px solid #fff;border-radius:9999px;display:grid;place-items:center;color:#fff;font-size:16px;font-weight:700;line-height:24px}
@media(min-width:561px){.theatre-picker{outline:2px solid #1ab7fd;outline-offset:2px}}
.hero-grid{width:60%;height:257.890625px;padding-bottom:40px;grid-template-rows:62.5px 29.6953125px 1fr}.hero-description{height:29.6953125px;margin:0;font-size:18px;line-height:29.6953125px}.hero-actions{align-self:end;gap:16px}.hero-button{box-sizing:border-box;width:152.421875px;min-width:152.421875px}.hero-learn{box-sizing:border-box;width:142.1484375px;height:48px;border:2px solid #fff;border-radius:9999px;display:grid;place-items:center;text-decoration:none}
@media(min-width:561px){.hero-footnote{display:none}}
@media(max-width:560px){.hero-grid{width:100%;height:329.09375px;grid-template-rows:87.5px 137.59375px 1fr}.hero-description{display:block;height:137.59375px;font-size:16px;line-height:26.3984375px}.hero-description>span:first-child{display:block;height:52.796875px}.hero .hero-description .hero-footnote{box-sizing:border-box;width:358px;height:52.796875px;margin:16px 0;color:rgb(197,207,211);font-size:16px;line-height:26.3984375px}.hero-footnote>span{display:inline-block;width:302.93px;height:47.898px;transform:translateY(2px)}.hero-actions{margin-bottom:0;gap:16px}.hero-button{width:139.3671875px;min-width:139.3671875px}.hero-learn{width:130.3828125px;height:48px}.movies-home:before{display:block}}
@media(max-width:560px){.theatre-picker{left:50%;top:21px;width:97%;height:802px}.theatre-picker>header,.theatre-picker-body{width:calc(100vw - 3.906px)}.theatre-picker>header{height:71px;padding:0 32px}.theatre-picker>header h1{font-size:18px;line-height:22.5px}.theatre-picker>header a{top:16px;right:32px;width:38px;height:38px}.theatre-picker-body{height:233px;padding:16px 32px}.theatre-picker-body>p{width:calc(100vw - 67.906px);height:24px;margin-bottom:16px}.theatre-picker-body form{width:calc(100vw - 67.906px);height:60px}.picker-input-box{width:calc(100vw - 67.906px);height:44px}.theatre-picker-body form input{width:calc(100vw - 111.906px);height:44px}.picker-location{height:21px;margin-top:16px;font-size:14px;line-height:21px}}
.theatre-picker-shell .showtimes-page{overflow:hidden;background:#000}.theatre-picker-shell .showtimes-page:before{content:"";position:fixed;inset:0;z-index:40;background:rgba(0,0,0,.5)}
.theatre-search input{min-width:0}
@media(max-width:560px){.page-head h1{overflow-wrap:anywhere}.theatre-search .button{flex:0 0 auto}}
.track-form{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;margin:24px 0}.track-form label{grid-column:1/-1;font-weight:700}.track-form input{min-width:0;padding:12px;border:1px solid #999}.track-result{margin-top:24px;gap:16px}.track-result strong{overflow-wrap:anywhere}
@media(max-width:560px){.track-form{grid-template-columns:1fr}.track-form label{grid-column:auto}.track-result{align-items:flex-start;flex-direction:column}}
.movies-home .movie-card[hidden]{display:none!important}.movies-home .movie-card:nth-child(n+5):not([hidden]){display:block!important}
.offer-nav{display:flex;flex-wrap:wrap;gap:24px;padding:24px 0;border-bottom:1px solid #ddd;font-weight:800}.offer-nav a{color:#b20d28}.offer-page-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:28px}.offer-card{overflow:hidden;border:1px solid #ddd;background:#fff;box-shadow:0 5px 20px #0001}.offer-card>img{display:block;width:100%;height:220px;object-fit:cover}.offer-card>div{padding:22px}.offer-card h2{margin:5px 0 10px;font-size:24px}.offer-card p:not(.eyebrow){min-height:66px;line-height:1.5}.feature-hero{min-height:430px;padding:100px 0;color:#fff;background-position:center;background-size:cover}.food-hero{background-image:linear-gradient(90deg,#000e,#0003),url('/local-assets/promo-snack-sip.jpg')}.feature-hero h1{max-width:650px;margin:10px 0;font-size:56px}.feature-hero p{max-width:610px;font-size:20px;line-height:1.5}.feature-detail{padding:70px 0}.feature-detail-grid{display:grid;grid-template-columns:1fr 1fr;align-items:center;gap:56px}.feature-detail-grid>img{width:100%;max-height:560px;object-fit:cover}.feature-detail-grid h1{font-size:48px}
.movie-detail-hero{background-position:center;background-size:cover}.detail-poster{width:290px;max-height:435px;object-fit:cover;box-shadow:0 12px 35px #000a}.detail-actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:24px}.movie-information{display:grid;grid-template-columns:1.4fr 1fr;gap:50px}.movie-information dl{margin:0}.movie-information dl>div{display:flex;justify-content:space-between;gap:20px;padding:13px 0;border-bottom:1px solid #ddd}.movie-information dt{font-weight:800}.movie-information dd{margin:0;text-align:right}.movie-gallery{grid-column:1/-1}.movie-gallery>div{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.movie-gallery img{width:100%;height:220px;object-fit:cover}
.captcha-control{margin:8px 0;padding:14px;border:1px solid #aaa;background:#f4f4f4;display:grid!important;grid-template-columns:auto 1fr auto;align-items:center;gap:12px;text-transform:none!important;letter-spacing:0!important}.captcha-control input{width:24px;height:24px}.captcha-control span{display:flex;flex-direction:column}.captcha-control small{margin-top:3px;color:#666;font-weight:400}.captcha-control b{display:grid;width:32px;height:32px;border-radius:50%;place-items:center;background:#2b72c8;color:#fff;font-size:20px}
.account-layout{display:grid;grid-template-columns:230px 1fr;gap:44px;padding-top:48px;padding-bottom:80px}.account-sidebar{position:sticky;top:110px;height:max-content;padding:24px;background:#171717;color:#fff;display:flex;flex-direction:column;gap:4px}.account-sidebar strong{padding:8px 10px 16px;font-size:24px}.account-sidebar a{padding:12px 10px;border-left:3px solid transparent}.account-sidebar a:hover,.account-sidebar a:focus{border-color:#d71920;background:#292929}.account-content{min-width:0}.account-content>section{margin-bottom:55px}.account-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.account-summary>div{padding:22px;background:#f4f1ec;display:flex;flex-direction:column;gap:8px}.account-summary strong{font-size:25px}.account-preferences{margin-top:0}
.showtimes-movie.has-times{height:260px}.showtimes-movie.has-times:after{bottom:0}.showtime-format{margin-top:4px!important;color:#a8b8bc}.showtimes-options{position:absolute;left:106px;right:0;bottom:26px;display:flex;flex-wrap:wrap;gap:8px}.showtimes-options .showtime{padding:9px 12px;border:1px solid #1ab7fd;border-radius:4px;color:#fff;background:#14262e}.showtimes-feature>img{display:block;width:476px;height:268px;object-fit:cover}.picker-divider+.picker-theatre{margin-top:0}
@media(max-width:700px){.offer-page-grid{grid-template-columns:1fr}.offer-card p:not(.eyebrow){min-height:0}.feature-detail-grid,.movie-information,.account-layout{grid-template-columns:1fr}.feature-detail-grid h1,.feature-hero h1{font-size:36px}.movie-gallery>div{grid-template-columns:1fr}.account-sidebar{position:static}.account-summary{grid-template-columns:1fr}.showtimes-movie.has-times{height:300px}.showtimes-options{left:0;bottom:40px}.showtimes-feature>img{width:100%;height:auto}}
"""


JS = r"""
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
function toast(message){const el=$('#toast');if(!el)return;el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2800)}
const alertClose=$('.alert-close');if(alertClose)alertClose.addEventListener('click',()=>{const strip=$('.alert-strip');strip.hidden=true;strip.style.display='none'});
$$('[data-open-search]').forEach(b=>b.addEventListener('click',()=>{const p=$('#search-panel'),nav=$('.nav'),menuButton=$('[data-menu]');if(nav)nav.classList.remove('open');if(menuButton)menuButton.setAttribute('aria-expanded','false');p.hidden=!p.hidden;if(!p.hidden)$('#global-q').focus()}));
const menu=$('[data-menu]');if(menu)menu.addEventListener('click',()=>{const nav=$('.nav');nav.classList.toggle('open');menu.setAttribute('aria-expanded',String(nav.classList.contains('open')))});
$$('[data-directory-tab]').forEach(tab=>tab.addEventListener('click',()=>{$$('[data-directory-tab]').forEach(item=>{const selected=item===tab;item.classList.toggle('on',selected);item.setAttribute('aria-selected',String(selected))});$$('[data-directory-panel]').forEach(panel=>{panel.hidden=panel.dataset.directoryPanel!==tab.dataset.directoryTab})}));
const currentLocation=$('[data-current-location]');if(currentLocation)currentLocation.addEventListener('click',()=>{const input=$('#theatre-q');if(input){input.value='New York';input.form.requestSubmit()}});
const favoriteTheatre=$('[data-favorite-theatre]');if(favoriteTheatre)favoriteTheatre.addEventListener('click',async()=>{if(favoriteTheatre.dataset.authenticated!=='true'){location.href='/login?next='+encodeURIComponent(location.pathname+location.search);return}const saved=favoriteTheatre.getAttribute('aria-pressed')!=='true';const current=await fetch('/api/preferences').then(r=>r.json());if(!current.ok){location.href='/login?next='+encodeURIComponent(location.pathname+location.search);return}const response=await fetch('/api/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({preferred_theatre:saved?favoriteTheatre.dataset.theatre:'',notifications_enabled:Boolean(current.preferences&&current.preferences.notifications_enabled),privacy_mode:(current.preferences&&current.preferences.privacy_mode)||'standard'})});const data=await response.json();if(data.ok){favoriteTheatre.setAttribute('aria-pressed',String(saved));const label=$('span',favoriteTheatre);if(label)label.textContent=saved?'Favorited':'Add Favorite';const theatreName=favoriteTheatre.dataset.theatreName||'Theatre';toast(saved?theatreName+' added to favorites':theatreName+' removed from favorites')}else toast(data.message||'Unable to update favorite theatre')});
let slide=0;$$('[data-slide]').forEach(b=>b.addEventListener('click',()=>{const dots=$$('.carousel-controls .dot');slide=b.dataset.slide==='next'?(slide+1)%dots.length:b.dataset.slide==='prev'?(slide+dots.length-1)%dots.length:Number(b.dataset.slide);dots.forEach((d,i)=>{d.classList.toggle('on',i===slide);d.setAttribute('aria-pressed',String(i===slide))})}));
$$('[data-movie-tab]').forEach(tab=>tab.addEventListener('click',()=>{$$('[data-movie-tab]').forEach(t=>{t.classList.toggle('on',t===tab);t.setAttribute('aria-selected',String(t===tab))});$$('.movies-home .movie-card').forEach(card=>card.hidden=card.dataset.movieCategory!==tab.dataset.movieTab)}));
const featuredSelect=$('.featured-select'),featuredMenu=$('#featured-menu');if(featuredSelect&&featuredMenu)featuredSelect.addEventListener('click',()=>{const open=featuredSelect.getAttribute('aria-expanded')!=='true';featuredSelect.setAttribute('aria-expanded',String(open));featuredMenu.hidden=!open});
const movieGenre=$('.movies-page-filter select[name="genre"]');if(movieGenre)movieGenre.addEventListener('change',()=>movieGenre.form.requestSubmit());
$$('[data-date-tab]').forEach(tab=>tab.addEventListener('click',()=>{$$('[data-date-tab]').forEach(t=>{t.classList.toggle('on',t===tab);t.setAttribute('aria-selected',String(t===tab))})}));
$$('[data-favorite]').forEach(button=>button.addEventListener('click',async()=>{const response=await fetch('/api/favorites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({movie_slug:button.dataset.favorite})});const data=await response.json();if(data.ok){button.classList.toggle('saved',data.saved);button.setAttribute('aria-pressed',String(data.saved));const title=button.dataset.title||'movie';button.setAttribute('aria-label',data.saved?`Remove ${title} from saved movies`:`Save ${title}`);if(button.classList.contains('heart-detail'))button.textContent=data.saved?'♥ Saved to My AMC':'♥ Save to My AMC';toast(data.saved?'Saved to My AMC':'Removed from saved movies')}else toast(data.message||'Unable to save')}));
const login=$('#login-form');if(login)login.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(login),response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:f.get('email'),password:f.get('password'),captcha:f.get('captcha')==='on'})}),data=await response.json();if(data.ok)location.href=f.get('next')||'/account';else $('.form-message',login).textContent=data.message});
const signup=$('#signup-form');if(signup)signup.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(signup),response=await fetch('/api/signup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:f.get('name'),email:f.get('email'),password:f.get('password'),plan:f.get('plan')||'insider'})}),data=await response.json();if(data.ok)location.href='/verify-account';else $('.form-message',signup).textContent=data.message});
const verifySignup=$('#verify-signup-form');if(verifySignup)verifySignup.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(verifySignup),response=await fetch('/api/signup/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:f.get('code')})}),data=await response.json();if(data.ok)location.href='/account';else $('.form-message',verifySignup).textContent=data.message});
const reset=$('#reset-form');if(reset)reset.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(reset),response=await fetch('/api/password-reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:f.get('email')})}),data=await response.json();if(data.ok)location.href='/password-reset/verify';else $('.form-message',reset).textContent=data.message});
const completeReset=$('#complete-reset-form');if(completeReset)completeReset.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(completeReset),response=await fetch('/api/password-reset/complete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:f.get('code'),new_password:f.get('new_password')})}),data=await response.json();if(data.ok)location.href='/account';else $('.form-message',completeReset).textContent=data.message});
const logout=$('#logout');if(logout)logout.addEventListener('click',async()=>{await fetch('/api/logout',{method:'POST'});location.href='/'});
const seats=$$('.seat'),place=$('#place-order');if(place){const ticketPrices={Adult:1599,Child:1199,Senior:1399},formatSurcharges={Standard:0,IMAX:499,'Dolby Cinema':399};const render=()=>{const chosen=seats.filter(s=>s.classList.contains('selected')).map(s=>s.dataset.seat),ticketType=$('#ticket-type').value,formatName=$('#format-name').value,attendee=$('#attendee-name').value.trim();$('#selected-seats').textContent=chosen.join(', ')||'None';$('#ticket-count').textContent=chosen.length;$('#review-ticket-type').textContent=ticketType;$('#review-format').textContent=formatName;$('#review-attendee').textContent=attendee||'Required';$('#order-total').textContent='$'+((chosen.length*(ticketPrices[ticketType]+formatSurcharges[formatName])+199)/100).toFixed(2);place.disabled=!chosen.length||!attendee};seats.forEach(seat=>seat.addEventListener('click',()=>{if(!seat.classList.contains('selected')&&seats.filter(s=>s.classList.contains('selected')).length>=8)return toast('Choose up to 8 seats');seat.classList.toggle('selected');render()}));['ticket-type','format-name','attendee-name'].forEach(id=>$('#'+id).addEventListener('input',render));render();place.addEventListener('click',async()=>{place.disabled=true;const chosen=seats.filter(s=>s.classList.contains('selected')).map(s=>s.dataset.seat),response=await fetch('/api/orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({movie_slug:place.dataset.movie,theatre_slug:place.dataset.theatre,showtime:place.dataset.time,seats:chosen,scenario:$('#scenario').value,ticket_type:$('#ticket-type').value,format_name:$('#format-name').value,attendee_name:$('#attendee-name').value})}),data=await response.json();if(data.ok){document.querySelector('.checkout-grid').innerHTML=`<div class="empty"><p class="eyebrow red">Order confirmed</p><h1>${data.order_id}</h1><p>Your local sandbox order total is ${data.total}.</p><a class="button" href="/account">View My AMC</a></div>`;toast(data.message)}else{toast(data.message||'Unable to complete order');place.disabled=false}})}
const manager=$('[data-order-id]');if(manager)$$('[data-order-action]',manager).forEach(button=>button.addEventListener('click',async()=>{const action=button.dataset.orderAction,payload={action};if(action==='reschedule')payload.showtime=$('[data-manage-showtime]',manager).value;if(action==='reminder')payload.reminder_enabled=manager.dataset.reminderCurrent!=='true';if(action==='concessions')payload.concessions=$$('[data-manage-concession]:checked',manager).map(item=>item.value);if(action==='notes')payload.notes=$('[data-manage-notes]',manager).value;if(action==='promo')payload.promo_code=$('[data-manage-promo]',manager).value;if(action==='share')payload.recipient=$('[data-manage-recipient]',manager).value;const response=await fetch(`/api/orders/${manager.dataset.orderId}/manage`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),data=await response.json();$(':scope > .form-message',manager).textContent=data.ok?`Order updated: ${data.order.status}`:data.message;if(data.ok)setTimeout(()=>location.reload(),350)}));
const reviewSave=$('[data-review-save]');if(manager&&reviewSave)reviewSave.addEventListener('click',async()=>{const response=await fetch(`/api/orders/${manager.dataset.orderId}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rating:Number($('[data-review-rating]',manager).value),visibility:$('[data-review-visibility]',manager).value,body:$('[data-review-body]',manager).value})}),data=await response.json(),message=$('.form-message',reviewSave.closest('fieldset'));message.textContent=data.ok?'Review saved locally.':data.message;if(data.ok)setTimeout(()=>location.reload(),350)});
const preferences=$('#preferences-form');if(preferences){fetch('/api/preferences').then(r=>r.json()).then(data=>{if(!data.ok)return;preferences.elements.preferred_theatre.value=data.preferences.preferred_theatre;preferences.elements.notifications_enabled.checked=data.preferences.notifications_enabled;preferences.elements.privacy_mode.value=data.preferences.privacy_mode});preferences.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(preferences),response=await fetch('/api/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({preferred_theatre:f.get('preferred_theatre'),notifications_enabled:f.get('notifications_enabled')==='on',privacy_mode:f.get('privacy_mode')})}),data=await response.json();$('.form-message',preferences).textContent=data.ok?'Preferences saved locally.':data.message})}
"""
