import praw
import streamlit as st
import sqlite3
import os
from datetime import datetime
from markdown import markdown
from concurrent.futures import ThreadPoolExecutor
import prawcore

# ======== API CONFIGURATION ======== #
REDDIT_CREDENTIALS = {
    "client_id": "wuCPhnYvuKQ8RHKRS2diZg",
    "client_secret": "iD0OsSpgMvpJjK-HmurmbANmyQxZ1w",
    "user_agent": "SEO Analyzer v2.0 (by /u/YOUR_USERNAME)"
}
# =================================== #

# Initialize Reddit API
try:
    reddit = praw.Reddit(**REDDIT_CREDENTIALS)
    reddit.user.me()  # Test API connection
except prawcore.exceptions.ResponseException as e:
    st.error(f"Reddit API Error: {str(e)}")
    st.stop()
except Exception as e:
    st.error(f"Authentication Failed: Check API credentials - {str(e)}")
    st.stop()

# ======== DATABASE CONFIG ======== #
def init_db():
    """Initialize database with proper FTS table"""
    try:
        conn = sqlite3.connect('seo_reddit.db')
        c = conn.cursor()
        
        # Main posts table
        c.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY,
                title TEXT,
                author TEXT,
                score INTEGER,
                url TEXT,
                created_utc INTEGER,
                body TEXT,
                subreddit TEXT,
                search_text TEXT
            )''')
        
        # FTS virtual table
        c.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts 
            USING fts5(
                id UNINDEXED,
                title,
                body,
                subreddit UNINDEXED,
                search_text,
                content='posts',
                content_rowid='rowid'
            )
        ''')
        
        # Create triggers to keep FTS in sync
        c.execute('''
            CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
                INSERT INTO posts_fts(rowid, id, title, body, subreddit, search_text)
                VALUES (new.rowid, new.id, new.title, new.body, new.subreddit, new.search_text);
            END;
        ''')
        
        c.execute('''
            CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN
                INSERT INTO posts_fts(posts_fts, rowid, id, title, body, subreddit, search_text)
                VALUES('delete', old.rowid, old.id, old.title, old.body, old.subreddit, old.search_text);
            END;
        ''')
        
        conn.commit()
    except sqlite3.Error as e:
        st.error(f"Database Error: {str(e)}")
        raise
    finally:
        conn.close()

# ======== DATA FETCHING ======== #
SUBREDDITS = ['SEO', 'bigseo','SEOnews', 'juststart', 'TechSEO',
    'DigitalMarketing', 'ContentMarketing', 'Blogging',
    'Affiliatemarketing', 'SocialMediaMarketing',
    'GoogleAnalytics', 'PPC', 'Wordpress', 'WebDev']
POST_LIMIT = 50

def fetch_subreddit_posts(subreddit):
    """Fetch and store posts for a subreddit"""
    try:
        conn = sqlite3.connect('seo_reddit.db')
        c = conn.cursor()
        
        for post in reddit.subreddit(subreddit).new(limit=POST_LIMIT):
            try:
                search_text = f"{post.title} {post.selftext} {subreddit}".lower()
                c.execute('''
                    INSERT OR REPLACE INTO posts 
                    VALUES (?,?,?,?,?,?,?,?,?)
                ''', (
                    post.id, post.title, str(post.author), post.score,
                    post.url, post.created_utc, post.selftext,
                    subreddit, search_text
                ))
            except prawcore.exceptions.ServerError:
                continue
        conn.commit()
    except Exception as e:
        st.error(f"Error in {subreddit}: {str(e)}")
    finally:
        conn.close()

def fetch_all_posts():
    """Fetch posts from all subreddits"""
    with ThreadPoolExecutor() as executor:
        executor.map(fetch_subreddit_posts, SUBREDDITS)

# ======== SEARCH FUNCTION ======== #
def search_posts(query):
    """Search posts using FTS"""
    try:
        conn = sqlite3.connect('seo_reddit.db')
        c = conn.cursor()
        
        # Verify FTS table exists
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='posts_fts'")
        if not c.fetchone():
            st.error("Search index missing! Please refresh data.")
            return []

        # Build safe query
        terms = [f'"{t}"' for t in query.strip().lower().split() if t]
        if not terms:
            return []
            
        fts_query = ' AND '.join(terms)
        
        c.execute('''
            SELECT p.* 
            FROM posts p
            WHERE rowid IN (
                SELECT rowid FROM posts_fts 
                WHERE posts_fts MATCH ?
                ORDER BY bm25(posts_fts)
            )
            ORDER BY score DESC
        ''', (fts_query,))
        
        return c.fetchall()
    except sqlite3.Error as e:
        st.error(f"Search error: {str(e)}")
        return []
    finally:
        conn.close()

# ======== STREAMLIT UI ======== #
st.set_page_config(page_title="Reddit SEO Analyzer", layout="wide")

# Custom CSS
st.markdown("""
<style>
      [data-testid="stAppViewContainer"] {
        background: var(--background-color);
    }
    
    .post-card {
        padding: 1.5rem;
        margin: 1.5rem 0;
        border-radius: 10px;
        background: var(--secondary-background-color);
        border: 1px solid var(--border-color);
        color: var(--text-color);
        transition: transform 0.2s;
    }
    
    .post-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    
    .post-title {
        color: var(--heading-color) !important;
        font-size: 1.4rem !important;
        margin-bottom: 0.5rem !important;
    }
    
    .comment {
        margin: 1rem 0;
        padding: 1rem;
        background: var(--background-color);
        border-radius: 8px;
        border-left: 4px solid #FF4500;
    }
    
    .subreddit-tag {
        background: #FF4500;
        color: white !important;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.9rem;
        font-weight: 500;
    }
    
    .metrics {
        color: var(--text-color);
        font-size: 0.9rem;
        opacity: 0.9;
    }
</style>
""", unsafe_allow_html=True)

# Main App
st.title("🔍 Reddit SEO Insights")
search_query = st.text_input("Search SEO topics (e.g., 'keyword density'):")

if st.button("Search"):
    if not search_query.strip():
        st.error("Please enter a search query")
        st.stop()
    
    with st.spinner(f'Finding discussions about "{search_query}"...'):
        try:
            results = search_posts(search_query)
            
            if not results:
                st.warning("No results found. Try different keywords.")
                st.stop()
            
            st.subheader(f"📚 Found {len(results)} relevant discussions")
            
            for post in results:
                # with st.container():
                #     post_id = post[0]
                #     created_date = datetime.utcfromtimestamp(int(post[5])).strftime('%d %b %Y')
                    
                #     st.markdown(f"""
                #     <div class="post-card">
                #         <div style="display: flex; align-items: center; margin-bottom: 1rem;">
                #             <span class="reddit-orange" style="font-weight: bold;">r/{post[7]}</span>
                #             <div style="margin-left: auto; color: #666;">
                #                 <span class="reddit-orange">▲ {post[3]}</span> • 
                #                 {created_date} • 
                #                 👤 {post[2] or 'Anonymous'}
                #             </div>
                #         </div>
                #         <h3>{post[1]}</h3>
                #         {markdown(post[6]) if post[6] else '<p style="color: #666;">[No text content]</p>'}
                #     """, unsafe_allow_html=True)
                    with st.container():
                        post_id = post[0]
                        created_date = datetime.utcfromtimestamp(int(post[5])).strftime('%d %b %Y')
    
                        st.markdown(f"""
                        <div class="post-card">
                            <div style="display: flex; align-items: center; margin-bottom: 1rem;">
                                <span class="subreddit-tag">r/{post[7]}</span>
                                <div style="margin-left: auto;" class="metrics">
                                    <span style="color: #FF4500;">▲ {post[3]}</span> • 
                                    📅 {created_date} • 
                                    👤 {post[2] or 'Anonymous'}
                                </div>
                            </div>
                            <div class="post-title">{post[1]}</div>
                            <div style="color: var(--text-color);">
                                {markdown(post[6]) if post[6] else '<p style="opacity: 0.7;">[No text content]</p>'}
                            </div>
                        """, unsafe_allow_html=True)
                    
                    # Show comments
                    try:
                        submission = reddit.submission(id=post_id)
                        submission.comments.replace_more(limit=0)
                        
                        if submission.comments:
                            st.markdown("**💬 Top Comments**")
                            for comment in submission.comments[:3]:
                                if comment.body in ('[removed]', '[deleted]'):
                                    continue
                                st.markdown(f"""
                                <div class="comment">
                                    <div style="margin-bottom: 0.5rem;">
                                        <strong>👤 {comment.author}</strong>
                                        <span class="reddit-orange">▲ {comment.score}</span>
                                    </div>
                                    {markdown(comment.body)}
                                </div>
                                """, unsafe_allow_html=True)
                    except Exception:
                        pass
                    
                    st.markdown("</div>", unsafe_allow_html=True)
        
        except Exception as e:
            st.error(f"Search failed: {str(e)}")

# Sidebar
with st.sidebar:
    st.subheader("Database Management")
    
    if st.button("🔄 Full Refresh Data"):
        try:
            with st.spinner("Rebuilding database..."):
                if os.path.exists('seo_reddit.db'):
                    os.remove('seo_reddit.db')
                init_db()
                fetch_all_posts()
                st.success("Database rebuilt successfully!")
        except Exception as e:
            st.error(f"Refresh failed: {str(e)}")
    
    if st.button("🔧 Rebuild Search Index"):
        try:
            conn = sqlite3.connect('seo_reddit.db')
            c = conn.cursor()
            c.execute('INSERT INTO posts_fts(posts_fts) VALUES("rebuild")')
            conn.commit()
            st.success("Search index rebuilt!")
        except sqlite3.Error as e:
            st.error(f"Rebuild failed: {str(e)}")
        finally:
            conn.close()
    
    st.markdown("---")
    st.markdown("**Subreddits monitored:**")
    for sub in SUBREDDITS:
        st.markdown(f"- r/{sub}")
    
    st.markdown("---")
    try:
        reddit.user.me()
        st.success("✅ API Connected")
    except Exception:
        st.error("❌ API Not Connected")

# Initial setup
if not os.path.exists('seo_reddit.db'):
    init_db()
    fetch_all_posts()
else:
    # Check for FTS table
    conn = sqlite3.connect('seo_reddit.db')
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='posts_fts'")
    if not c.fetchone():
        st.warning("Old database format detected - migrating to new version...")
        conn.close()
        os.remove('seo_reddit.db')
        init_db()
        fetch_all_posts()
    else:
        conn.close()

# How to run:
# 1. pip install praw streamlit markdown
# 2. Replace API credentials
# 3. streamlit run app.py