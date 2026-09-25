create schema if not exists nem;

grant usage on schema nem to service_role;
alter default privileges for role postgres in schema nem
grant all on tables to service_role;

create table if not exists nem.dispatch_price (
    regionid text not null,
    settlementdate timestamp without time zone not null,
    intervention smallint not null,
    rrp numeric not null,
    created_at timestamp with time zone not null default now(),
    constraint dispatch_price_pkey primary key (regionid, settlementdate, intervention)
) tablespace pg_default;

create table if not exists nem.dispatch_regionsum (
    regionid text not null,
    settlementdate timestamp without time zone not null,
    intervention smallint not null,
    totaldemand numeric not null,
    created_at timestamp with time zone not null default now(),
    constraint dispatch_regionsum_pkey primary key (regionid, settlementdate, intervention)
) tablespace pg_default;


create table if not exists nem.dispatch_interconnection (
    settlementdate timestamp without time zone not null,
    from_regionid text not null,
    to_regionid text not null,
    intervention smallint not null,
    mwflow numeric not null,
    created_at timestamp with time zone not null default now(),
    constraint dispatch_interconnection_pkey primary key (settlementdate, from_regionid, to_regionid, intervention)
) tablespace pg_default;

create table if not exists nem.p5_min_regionsolution (
    regionid text not null,
    run_datetime timestamp without time zone not null,
    interval_datetime timestamp without time zone not null,
    publication_datetime timestamp without time zone not null,
    intervention smallint not null,
    rrp numeric not null,
    totaldemand numeric not null,
    netinterchange numeric not null,
    created_at timestamp with time zone not null default now(),
    constraint p5_min_regionsolution_pkey primary key (regionid, run_datetime, interval_datetime, intervention)
)  tablespace pg_default;

create table if not exists nem.predispatch_region_prices (
    regionid text not null,
    run_datetime timestamp without time zone not null,
    datetime timestamp without time zone not null,
    publication_datetime timestamp without time zone not null,
    intervention smallint not null,
    rrp numeric not null,
    created_at timestamp with time zone not null default now(),
    constraint predispatch_region_prices_pkey primary key (regionid, run_datetime, datetime, intervention)
) tablespace pg_default;

create table if not exists nem.predispatch_region_solution (
    regionid text not null,
    run_datetime timestamp without time zone not null,
    datetime timestamp without time zone not null,
    publication_datetime timestamp without time zone not null,
    intervention smallint not null,
    totaldemand numeric not null,
    netinterchange numeric not null,
    created_at timestamp with time zone not null default now(),
    constraint predispatch_region_solution_pkey primary key (regionid, run_datetime, datetime, intervention)
) tablespace pg_default;

alter table nem.dispatch_price enable row level security;
alter table nem.dispatch_regionsum enable row level security;
alter table nem.dispatch_interconnection enable row level security;
alter table nem.p5_min_regionsolution enable row level security;
alter table nem.predispatch_region_prices enable row level security;
alter table nem.predispatch_region_solution enable row level security;

revoke all on table nem.dispatch_price from anon, authenticated;
revoke all on table nem.dispatch_regionsum from anon, authenticated;
revoke all on table nem.dispatch_interconnection from anon, authenticated;
revoke all on table nem.p5_min_regionsolution from anon, authenticated;
revoke all on table nem.predispatch_region_prices from anon, authenticated;
revoke all on table nem.predispatch_region_solution from anon, authenticated;

grant select, insert on table nem.dispatch_price to service_role;
grant select, insert on table nem.dispatch_regionsum to service_role;
grant select, insert on table nem.dispatch_interconnection to service_role;
grant select, insert on table nem.p5_min_regionsolution to service_role;
grant select, insert on table nem.predispatch_region_prices to service_role;
grant select, insert on table nem.predispatch_region_solution to service_role;