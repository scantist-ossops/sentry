import styled from '@emotion/styled';

import DatePageFilter from 'sentry/components/datePageFilter';
import EnvironmentPageFilter from 'sentry/components/environmentPageFilter';
import PageFilterBar from 'sentry/components/organizations/pageFilterBar';
import PageFiltersContainer from 'sentry/components/organizations/pageFilters/container';
import ProjectPageFilter from 'sentry/components/projectPageFilter';
import {space} from 'sentry/styles/space';
import {useApiQuery} from 'sentry/utils/queryClient';
import {useLocation} from 'sentry/utils/useLocation';
import useOrganization from 'sentry/utils/useOrganization';
import usePageFilters from 'sentry/utils/usePageFilters';

export default function Funnel() {
  const organization = useOrganization();
  const {selection} = usePageFilters();
  const location = useLocation();
  // useApiQuery<any>(
  //   [
  //     `/organizations/${organization.slug}/funnel/`,
  //     {
  //       query: location.query,
  //     },
  //   ],
  //   {
  //     staleTime: Infinity,
  //   }
  // );
  return (
    <Wrapper>
      <h1>Funnel</h1>
      <PageFiltersContainer>
        <PageFilterBar condensed>
          <ProjectPageFilter />
          <EnvironmentPageFilter />
          <DatePageFilter alignDropdown="left" />
        </PageFilterBar>
      </PageFiltersContainer>
      Hi
    </Wrapper>
  );
}

const Wrapper = styled('div')`
  padding: ${space(3)};
`;