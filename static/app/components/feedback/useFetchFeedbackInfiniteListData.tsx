import {useCallback, useEffect, useRef, useState} from 'react';
import {Index, IndexRange} from 'react-virtualized';
import moment from 'moment';

import {ApiResult, Client} from 'sentry/api';
import hydrateFeedbackRecord from 'sentry/components/feedback/hydrateFeedbackRecord';
import {Organization} from 'sentry/types';
import formatDuration from 'sentry/utils/duration/formatDuration';
import Dispatch from 'sentry/utils/eventDispatcher';
import {
  FeedbackItemResponse,
  HydratedFeedbackItem,
} from 'sentry/utils/feedback/item/types';
import {EMPTY_QUERY_VIEW, QueryView} from 'sentry/utils/feedback/list/types';
import parseLinkHeader from 'sentry/utils/parseLinkHeader';
import {decodeInteger} from 'sentry/utils/queryString';
import useApi from 'sentry/utils/useApi';
import useOrganization from 'sentry/utils/useOrganization';

const PER_PAGE = 10;

type Unsubscribe = () => void;

function startDateFromQueryView({start, statsPeriod}: QueryView): Date {
  if (start) {
    return new Date(start);
  }
  if (statsPeriod) {
    const value = parseInt(statsPeriod, 10);
    const unit = statsPeriod.endsWith('m')
      ? 'min'
      : statsPeriod.endsWith('h')
      ? 'hour'
      : statsPeriod.endsWith('d')
      ? 'day'
      : statsPeriod.endsWith('w')
      ? 'week'
      : undefined;
    if (unit) {
      const msdifference = formatDuration({
        precision: 'ms',
        style: 'count',
        duration: [value, unit],
      });
      return moment.utc().subtract(msdifference, 'ms').toDate();
    }
  }
  throw new Error('Must pass either start or statsPeriod');
}

function endDateFromQueryView({end}: QueryView): Date {
  if (end) {
    return new Date(end);
  }
  return new Date();
}

class InfiniteListLoader {
  private dispatch = new Dispatch();

  private timestampToFeedback = new Map<number, HydratedFeedbackItem>();

  public hasPrev: undefined | boolean = undefined;
  public hasMore: undefined | boolean = undefined;
  public totalHits: undefined | number = undefined;

  private isFetching = false;
  public isFetchingNext = false;
  public isFetchingPrev = false;

  constructor(
    private api: Client,
    private organization: Organization,
    private queryView: QueryView,
    private initialDate: Date
  ) {
    if (!queryView.start && !queryView.statsPeriod) {
      return;
    }
    this.fetch({
      start: startDateFromQueryView(queryView),
      end: this.initialDate,
      sort: '-timestamp',
      perPage: PER_PAGE,
    }).then(results => {
      this.totalHits = results.hits;
      this.didFetchNext(results);
    });
  }

  get feedbacks() {
    const initialDateTime = this.initialDate.getTime();
    const timestamps = Array.from(this.timestampToFeedback.keys())
      .filter(timestamp => timestamp < initialDateTime)
      .sort()
      .reverse();

    const feedbacks = timestamps.map(timestamp =>
      this.timestampToFeedback.get(timestamp)
    );
    return feedbacks;
  }

  setFeedback(feedbackId: string, feedback: undefined | HydratedFeedbackItem) {
    const old = this.feedbacks.find(fb => fb?.feedback_id === feedbackId);
    if (old) {
      if (!feedback) {
        this.timestampToFeedback.delete(old.timestamp.getTime());
      } else {
        this.timestampToFeedback.set(old.timestamp.getTime(), feedback);
      }
    }
  }

  onChange(handler: () => void): Unsubscribe {
    this.dispatch.addEventListener('change', handler);
    return () => this.dispatch.removeEventListener('change', handler);
  }

  private get minDatetime() {
    return (
      new Date(Math.min(...Array.from(this.timestampToFeedback.keys()))) ?? new Date()
    );
  }

  private get maxDatetime() {
    return (
      new Date(Math.max(...Array.from(this.timestampToFeedback.keys()))) ?? new Date()
    );
  }

  public resetInitialTimestamp() {
    this.initialDate = new Date(this.maxDatetime);
  }

  private async fetch({
    end,
    perPage,
    sort,
    start,
  }: {
    end: Date;
    perPage: number;
    sort: 'timestamp' | '-timestamp';
    start: Date;
  }) {
    if (this.isFetching) {
      return {
        feedbacks: [],
        hasNextPage: undefined,
        hits: 0,
      };
    }

    this.isFetching = true;

    const [data, , resp]: ApiResult<undefined | FeedbackItemResponse[]> =
      await this.api.requestPromise(
        `/organizations/${this.organization.slug}/feedback/`,
        {
          includeAllArgs: true,
          query: {
            ...this.queryView,
            statsPeriod: undefined,
            cursor: `0:0:0`,
            per_page: perPage,
            sort,
            start: start.toISOString(),
            end: end.toISOString(),
          },
        }
      );

    this.isFetching = false;

    const hits = decodeInteger(resp?.getResponseHeader('X-Hits'), 0);
    const nextPage = parseLinkHeader(resp?.getResponseHeader('Link') ?? null).cursor;
    const feedbacks = data?.map(hydrateFeedbackRecord);
    feedbacks?.forEach(feedback => {
      this.timestampToFeedback.set(feedback.timestamp.getTime(), feedback);
    });

    return {
      feedbacks,
      hasNextPage: Boolean(nextPage),
      hits,
    };
  }

  public async fetchNext(perPage: number = PER_PAGE) {
    if (this.hasMore !== true) {
      // Skip the request if we either:
      // - Have not yet got the first results back
      // - or, we know there are no more results to fetch
      return;
    }

    this.isFetchingNext = true;
    const result = await this.fetch({
      end: this.minDatetime,
      perPage,
      sort: '-timestamp',
      start: startDateFromQueryView(this.queryView),
    });
    this.isFetchingNext = false;
    this.didFetchNext(result);
  }

  public async fetchPrev(perPage: number = PER_PAGE) {
    if (this.hasPrev !== false) {
      // Skip the request if:
      // - We know there are no more results to fetch
      return;
    }

    this.isFetchingPrev = true;
    const result = await this.fetch({
      end: endDateFromQueryView(this.queryView),
      perPage,
      sort: 'timestamp',
      start: this.maxDatetime,
    });
    this.isFetchingPrev = false;
    this.didFetchPrev(result);
  }

  private didFetchNext = ({hasNextPage}) => {
    const now = Date.now();
    this.hasMore = hasNextPage || this.minDatetime.getTime() < now;
    this.dispatch.dispatchEvent(new Event('change'));
  };

  private didFetchPrev = ({hasNextPage}) => {
    const now = Date.now();
    this.hasPrev = hasNextPage || (this.maxDatetime.getTime() ?? now) > now;
    this.dispatch.dispatchEvent(new Event('change'));
  };
}

export const EMPTY_INFINITE_LIST_DATA: ReturnType<
  typeof useFetchFeedbackInfiniteListData
> = {
  countLoadedRows: 0,
  getRow: () => undefined,
  isError: false,
  isFetchingNext: false,
  isFetchingPrev: false,
  isLoading: false,
  isRowLoaded: () => false,
  loadMoreRows: () => Promise.resolve(),
  queryView: EMPTY_QUERY_VIEW,
  setFeedback: () => undefined,
  totalHits: 0,
};

type State = {
  isFetchingNext: boolean;
  isFetchingPrev: boolean;
  items: (HydratedFeedbackItem | undefined)[];
  totalHits: undefined | number;
};

export default function useFetchFeedbackInfiniteListData({
  queryView,
  initialDate,
}: {
  initialDate: Date;
  queryView: QueryView;
}) {
  const api = useApi();
  const organization = useOrganization();

  const loaderRef = useRef<InfiniteListLoader>();
  const [state, setState] = useState<State>({
    items: [],
    totalHits: undefined,
    isFetchingNext: false,
    isFetchingPrev: false,
  });

  useEffect(() => {
    const loader = new InfiniteListLoader(api, organization, queryView, initialDate);
    loaderRef.current = loader;

    return loader.onChange(() => {
      const {totalHits, isFetchingNext, isFetchingPrev} = loader;
      setState({
        items: loader.feedbacks,
        totalHits,
        isFetchingNext,
        isFetchingPrev,
      });
    });
  }, [api, organization, queryView, initialDate]);

  const getRow = useCallback(
    ({index}: Index): HydratedFeedbackItem | undefined => state.items[index] ?? undefined,
    [state.items]
  );

  const isRowLoaded = useCallback(
    ({index}: Index) => state.items[index] !== undefined,
    [state.items]
  );

  const loadMoreRows = useCallback(
    ({startIndex, stopIndex}: IndexRange) =>
      loaderRef.current?.fetchNext(stopIndex - startIndex) ?? Promise.resolve(),
    []
  );

  const setFeedback = useCallback(
    (feedbackId: string, feedback: undefined | HydratedFeedbackItem) =>
      loaderRef.current?.setFeedback(feedbackId, feedback),
    []
  );

  useEffect(() => {
    loadMoreRows({startIndex: 0, stopIndex: PER_PAGE});
  }, [loadMoreRows]);

  const {totalHits, isFetchingNext, isFetchingPrev} = state;
  return {
    countLoadedRows: state.items.length,
    getRow,
    isError: false,
    isFetchingNext,
    isFetchingPrev,
    isLoading: false,
    isRowLoaded,
    loadMoreRows,
    queryView,
    setFeedback,
    totalHits,
  };
}