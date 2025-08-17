-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create ENUM types
CREATE TYPE platform_type AS ENUM ('linkedin', 'facebook', 'instagram', 'tiktok', 'twitter', 'bluesky', 'website');
CREATE TYPE jurisdiction_level AS ENUM ('state', 'city', 'county');
CREATE TYPE signal_status AS ENUM ('new', 'triaged', 'dismissed');
CREATE TYPE calendar_source AS ENUM ('usvote', 'ap', 'manual');
CREATE TYPE limit_type AS ENUM ('fixed', 'no_limit', 'aggregate');

-- Candidates table
CREATE TABLE candidates (
    candidate_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name VARCHAR(255) NOT NULL,
    preferred_name VARCHAR(255),
    party VARCHAR(100),
    jurisdiction_type VARCHAR(100),
    jurisdiction_name VARCHAR(255),
    state VARCHAR(2),
    office VARCHAR(255),
    district VARCHAR(100),
    election_cycle INTEGER,
    status VARCHAR(100),
    incumbent BOOLEAN DEFAULT FALSE,
    current_position VARCHAR(255),
    bio_summary TEXT,
    source_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Committees table
CREATE TABLE committees (
    committee_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    jurisdiction VARCHAR(255),
    state VARCHAR(2),
    type VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Candidate-Committee relationships
CREATE TABLE candidate_committees (
    candidate_id UUID REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    committee_id UUID REFERENCES committees(committee_id) ON DELETE CASCADE,
    role VARCHAR(100),
    PRIMARY KEY (candidate_id, committee_id)
);

-- Filings table
CREATE TABLE filings (
    filing_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id UUID REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    committee_id UUID REFERENCES committees(committee_id) ON DELETE SET NULL,
    jurisdiction VARCHAR(255),
    office VARCHAR(255),
    receipt_date DATE,
    period_start DATE,
    period_end DATE,
    filing_type VARCHAR(100),
    total_receipts NUMERIC(15,2),
    total_disbursements NUMERIC(15,2),
    cash_on_hand NUMERIC(15,2),
    debts_owed NUMERIC(15,2),
    source_url TEXT,
    raw_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Social profiles table
CREATE TABLE social_profiles (
    profile_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id UUID REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    platform platform_type NOT NULL,
    url TEXT,
    handle VARCHAR(255),
    followers INTEGER,
    confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),
    last_checked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Media mentions table
CREATE TABLE media_mentions (
    mention_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id UUID REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    title TEXT,
    url TEXT,
    publisher VARCHAR(255),
    published_at DATE,
    confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),
    snippet TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Seat profiles table
CREATE TABLE seat_profiles (
    seat_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    jurisdiction_type VARCHAR(100),
    jurisdiction_name VARCHAR(255),
    state VARCHAR(2),
    office VARCHAR(255),
    district VARCHAR(100),
    seat_current_holder_party VARCHAR(100),
    seat_incumbent_running BOOLEAN,
    pvi TEXT,
    last_result_year INTEGER,
    last_margin NUMERIC(5,2),
    primary_date DATE,
    runoff_date DATE,
    general_date DATE,
    calendar_source calendar_source,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Signals table
CREATE TABLE signals (
    signal_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id UUID REFERENCES candidates(candidate_id) ON DELETE SET NULL,
    source TEXT,
    account_handle VARCHAR(255),
    posted_at TIMESTAMP WITH TIME ZONE,
    text TEXT,
    url TEXT,
    status signal_status DEFAULT 'new',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Jurisdiction profiles table
CREATE TABLE jurisdiction_profiles (
    jurisdiction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    level jurisdiction_level NOT NULL,
    state VARCHAR(2),
    avg_spend_last_cycle NUMERIC(15,2),
    median_spend_last_cycle NUMERIC(15,2),
    high_spend_last_cycle NUMERIC(15,2),
    contribution_limit_individual NUMERIC(10,2),
    contribution_limit_pac NUMERIC(10,2),
    limit_type limit_type DEFAULT 'fixed',
    has_public_financing BOOLEAN DEFAULT FALSE,
    matching_rate TEXT,
    always_include BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX idx_candidates_election_cycle ON candidates(election_cycle);
CREATE INDEX idx_candidates_state ON candidates(state);
CREATE INDEX idx_candidates_office ON candidates(office);
CREATE INDEX idx_candidates_party ON candidates(party);
CREATE INDEX idx_candidates_jurisdiction ON candidates(jurisdiction_type, jurisdiction_name);

CREATE INDEX idx_filings_candidate_id ON filings(candidate_id);
CREATE INDEX idx_filings_receipt_date ON filings(receipt_date);
CREATE INDEX idx_filings_jurisdiction ON filings(jurisdiction);

CREATE INDEX idx_social_profiles_candidate_id ON social_profiles(candidate_id);
CREATE INDEX idx_social_profiles_platform ON social_profiles(platform);

CREATE INDEX idx_media_mentions_candidate_id ON media_mentions(candidate_id);
CREATE INDEX idx_media_mentions_published_at ON media_mentions(published_at);
CREATE INDEX idx_media_mentions_publisher ON media_mentions(publisher);

CREATE INDEX idx_seat_profiles_state_office ON seat_profiles(state, office);
CREATE INDEX idx_seat_profiles_primary_date ON seat_profiles(primary_date);

CREATE INDEX idx_signals_status ON signals(status);
CREATE INDEX idx_signals_posted_at ON signals(posted_at);

CREATE INDEX idx_jurisdiction_profiles_state ON jurisdiction_profiles(state);
CREATE INDEX idx_jurisdiction_profiles_level ON jurisdiction_profiles(level);

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Add updated_at triggers to all tables
CREATE TRIGGER update_candidates_updated_at BEFORE UPDATE ON candidates FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_committees_updated_at BEFORE UPDATE ON committees FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_filings_updated_at BEFORE UPDATE ON filings FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_social_profiles_updated_at BEFORE UPDATE ON social_profiles FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_media_mentions_updated_at BEFORE UPDATE ON media_mentions FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_seat_profiles_updated_at BEFORE UPDATE ON seat_profiles FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_signals_updated_at BEFORE UPDATE ON signals FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_jurisdiction_profiles_updated_at BEFORE UPDATE ON jurisdiction_profiles FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
