import { makeStyles } from '@material-ui/core';
import mark from '../../assets/otternet-mark.png';

const useStyles = makeStyles({
  img: {
    height: 28,
    width: 28,
    borderRadius: 6,
    display: 'block',
  },
});

export const LogoIcon = () => {
  const classes = useStyles();

  return <img className={classes.img} src={mark} alt="Otter-net" />;
};
