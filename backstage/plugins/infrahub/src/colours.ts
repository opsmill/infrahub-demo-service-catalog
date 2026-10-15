import { useTheme } from '@material-ui/core/styles';

/**
 * What the panels paint things with, taken from the MUI theme rather than
 * hardcoded here.
 *
 * This is the layering that makes the panels reusable: the plugin decides which
 * *role* a colour plays, and the app's theme decides what that role looks like.
 * An app that installs this plugin gets its own brand for free, and one that
 * installs no theme gets MUI's defaults, which are already distinct enough to
 * read.
 */
export function useKindColours() {
  const { palette } = useTheme();

  return {
    /** A service -- the subject of every graph it appears in. */
    service: palette.primary.main,
    /** Devices, interfaces, racks. */
    device: palette.info.main,
    /** Switches, so a rack tells them from routers at a glance. */
    deviceAlt: palette.success.main,
    /** Prefixes, addresses, VLANs. */
    address: palette.warning.main,
    /** Sites and racks as places. */
    place: palette.secondary.main,
    /** Anything unrecognised. */
    neutral: palette.text.disabled,
  };
}

/**
 * Status is a signal an operator scans for, not branding, so it comes from
 * Backstage's own `palette.status` -- which exists for exactly this -- and stays
 * conventional: green means fine and red means it is not.
 */
export function useStatusColours() {
  const theme = useTheme();
  const status = theme.palette.status;

  return {
    ok: status.ok,
    idle: status.aborted,
    pending: status.pending,
    error: status.error,
  };
}
