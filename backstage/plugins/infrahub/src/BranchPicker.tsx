import { useEffect, useRef, useState } from 'react';
import Menu from '@material-ui/core/Menu';
import MenuItem from '@material-ui/core/MenuItem';
import ListSubheader from '@material-ui/core/ListSubheader';
import CallSplitIcon from '@material-ui/icons/CallSplit';
import { SidebarItem } from '@backstage/core-components';
import { useInfrahubQuery } from './client';
import { DEFAULT_BRANCH } from '@opsmill/backstage-plugin-infrahub-common';
import { useInfrahubBranch } from './branch';

const QUERY = `
  {
    Branch {
      name
      is_default
    }
  }
`;

type Branches = { Branch: { name: string; is_default: boolean }[] };

/**
 * Switches which Infrahub branch the visual panels query. Sits in the sidebar
 * because it applies to every page, not to one entity.
 */
export function BranchPicker() {
  const { branch, setBranch } = useInfrahubBranch();
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLDivElement>(null);
  // Always asked of the default branch, so the list survives the selected
  // branch being deleted.
  const { data } = useInfrahubQuery<Branches>(
    QUERY,
    {},
    [],
    false,
    DEFAULT_BRANCH,
  );

  const branches = data?.Branch ?? [];

  // A branch can be deleted while it is still the stored selection -- which
  // this session does constantly -- and every panel would then error. Fall
  // back to the default as soon as we know it is gone.
  useEffect(() => {
    if (branches.length > 0 && !branches.some(entry => entry.name === branch)) {
      setBranch(DEFAULT_BRANCH);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, branch]);
  const main = branches.filter(entry => entry.is_default);
  const others = branches
    .filter(entry => !entry.is_default)
    .sort((a, b) => a.name.localeCompare(b.name));

  const choose = (next: string) => {
    setBranch(next);
    setOpen(false);
  };

  return (
    <div ref={anchor}>
      <SidebarItem
        icon={CallSplitIcon}
        text={branch}
        onClick={() => setOpen(true)}
      />
      <Menu
        open={open}
        anchorEl={anchor.current}
        onClose={() => setOpen(false)}
        anchorOrigin={{ vertical: 'center', horizontal: 'right' }}
        transformOrigin={{ vertical: 'center', horizontal: 'left' }}
      >
        <ListSubheader>Infrahub branch</ListSubheader>
        {[...main, ...others].map(entry => (
          <MenuItem
            key={entry.name}
            selected={entry.name === branch}
            onClick={() => choose(entry.name)}
          >
            {entry.name}
            {entry.is_default ? ' (default)' : ''}
          </MenuItem>
        ))}
        {branches.length === 0 && (
          <MenuItem onClick={() => choose(DEFAULT_BRANCH)}>
            {DEFAULT_BRANCH}
          </MenuItem>
        )}
      </Menu>
    </div>
  );
}
