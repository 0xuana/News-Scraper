CREATE TABLE IF NOT EXISTS news (
    id bigint PRIMARY KEY,
    rec_time bigint NOT NULL,
    published_at timestamptz NOT NULL,
    update_time timestamptz,
    title text,
    content text,
    important boolean,
    important_db boolean,
    selection boolean,
    app_push boolean,
    source text,
    view_num bigint,
    support_num bigint,
    oppose_num bigint,
    comment_num bigint,
    share_num bigint,
    agq_share_num bigint,
    url text,
    theme text,
    theme_quotes jsonb,
    concept_list jsonb,
    stock_info jsonb,
    stock_quotes jsonb,
    stock_code text,
    quote_plate jsonb,
    is_24_hour_hot_news boolean,
    jump_24_hour_hot_list boolean,
    express_hot_state text,
    raw_json jsonb NOT NULL,
    first_collected_at timestamptz NOT NULL DEFAULT now(),
    last_collected_at timestamptz NOT NULL DEFAULT now(),
    mutable_until timestamptz NOT NULL DEFAULT (now() + interval '1 month'),
    finalized_at timestamptz
);

CREATE INDEX IF NOT EXISTS news_rec_time_idx ON news (rec_time);

CREATE TABLE IF NOT EXISTS news_stock (
    news_id bigint NOT NULL REFERENCES news(id) ON DELETE CASCADE,
    stock_code text NOT NULL,
    stock_name text NOT NULL,
    PRIMARY KEY (news_id, stock_code)
);

CREATE TABLE IF NOT EXISTS news_theme (
    news_id bigint NOT NULL REFERENCES news(id) ON DELETE CASCADE,
    theme_id text NOT NULL,
    theme_name text NOT NULL,
    PRIMARY KEY (news_id, theme_id)
);

CREATE TABLE IF NOT EXISTS news_topic (
    news_id bigint NOT NULL REFERENCES news(id) ON DELETE CASCADE,
    topic_id text NOT NULL,
    topic_title text NOT NULL,
    is_hot boolean,
    old_title text,
    PRIMARY KEY (news_id, topic_id)
);

CREATE TABLE IF NOT EXISTS crawler_state (
    collector_name text PRIMARY KEY,
    cursor bigint NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
