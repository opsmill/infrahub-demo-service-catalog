import { makeStyles } from '@material-ui/core';
import logo from '../../assets/otternet-logo.png';

const useStyles = makeStyles({
  // The logo carries a light ground of its own, so it sits on the dark sidebar
  // as one deliberate block rather than a cut-out with a halo.
  img: {
    height: 40,
    width: 'auto',
    borderRadius: 4,
    display: 'block',
  },
});

export const LogoFull = () => {
  const classes = useStyles();

  return <img className={classes.img} src={logo} alt="Otter-net" />;
};
