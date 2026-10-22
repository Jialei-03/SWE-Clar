import React, {useEffect, useRef, useState} from 'react';
import {View, Text, TextInput, Pressable, ScrollView, StyleSheet} from 'react-native';
import {api, origin, getToken, setToken, clearToken} from './api';
import {player} from './player';

const emptyReport = () => ({count: 0, latest: {}, overall: {}});

const Button = ({title, onPress, testID, disabled = false}) => (
  <Pressable
    testID={testID}
    accessibilityRole="button"
    disabled={disabled}
    onPress={onPress}
    style={[styles.button, disabled && styles.disabledButton]}
  >
    <Text>{title}</Text>
  </Pressable>
);

export default function App() {
  const [signed, setSigned] = useState(false);
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [tab, setTab] = useState('Audio');
  const [tracks, setTracks] = useState([]);
  const [goals, setGoals] = useState([]);
  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers] = useState({});
  const [report, setReport] = useState(emptyReport);
  const [mode, setMode] = useState('latest');
  const [title, setTitle] = useState('');
  const [product, setProduct] = useState('');
  const [store, setStore] = useState('');
  const [transaction, setTransaction] = useState('');
  const [subscriptions, setSubscriptions] = useState([]);
  const [progress, setProgress] = useState({position: 0, isPlaying: false});
  const [loggingIn, setLoggingIn] = useState(false);

  const mounted = useRef(true);
  const session = useRef(0);
  const token = useRef('');
  const refreshSequence = useRef(0);
  const loginAttempt = useRef(0);
  const goalSequence = useRef(0);

  const isCurrent = generation => (
    mounted.current && session.current === generation && Boolean(token.current)
  );

  const clearUserData = (clearLogin = false) => {
    setTab('Audio');
    setTracks([]);
    setGoals([]);
    setQuestions([]);
    setAnswers({});
    setReport(emptyReport());
    setMode('latest');
    setTitle('');
    setProduct('');
    setStore('');
    setTransaction('');
    setSubscriptions([]);
    setProgress({position: 0, isPlaying: false});
    setError('');
    if (clearLogin) setLogin('');
    setPassword('');
  };

  useEffect(() => {
    const timer = setInterval(() => {
      const generation = session.current;
      player.snapshot().then(snapshot => {
        if (mounted.current && generation === session.current && token.current) {
          setProgress(snapshot);
        }
      }).catch(() => {});
    }, 200);
    return () => {
      mounted.current = false;
      clearInterval(timer);
      void player.clear();
    };
  }, []);

  const refresh = async (generation, requestToken) => {
    const sequence = ++refreshSequence.current;
    try {
      const [nextTracks, nextGoals, nextQuestions, nextReport, nextSubscriptions] = await Promise.all([
        api('/tracks', undefined, {token: requestToken}),
        api('/goals', undefined, {token: requestToken}),
        api('/questions', undefined, {token: requestToken}),
        api('/report', undefined, {token: requestToken}),
        api('/subscriptions', undefined, {token: requestToken}),
      ]);
      if (!isCurrent(generation) || sequence !== refreshSequence.current) return false;
      setTracks(nextTracks);
      setGoals(nextGoals);
      setQuestions(nextQuestions);
      setReport(nextReport);
      setSubscriptions(nextSubscriptions);
      return true;
    } catch (reason) {
      if (isCurrent(generation) && sequence === refreshSequence.current) {
        setError(reason && reason.message ? reason.message : 'request_failed');
        throw reason;
      }
      return false;
    }
  };

  const signIn = async () => {
    if (loggingIn) return;
    const attempt = ++loginAttempt.current;
    const enteredLogin = login;
    const enteredPassword = password;
    setLoggingIn(true);
    setError('');
    try {
      const result = await api('/login', {
        login: enteredLogin,
        password: enteredPassword,
      }, {token: ''});
      if (!mounted.current || attempt !== loginAttempt.current || !result || typeof result.token !== 'string') {
        return;
      }
      // A successful login starts a fresh client identity.  Nothing from an
      // earlier account is retained while its reads are still in flight.
      session.current += 1;
      refreshSequence.current += 1;
      token.current = result.token;
      setToken(result.token);
      void player.clear();
      setPassword('');
      clearUserData(false);
      setSigned(true);
      await refresh(session.current, result.token);
    } catch (reason) {
      if (mounted.current && attempt === loginAttempt.current) {
        setError(reason && reason.message ? reason.message : 'request_failed');
      }
    } finally {
      if (mounted.current && attempt === loginAttempt.current) setLoggingIn(false);
    }
  };

  const logout = () => {
    const oldToken = token.current || getToken();
    // Invalidate the session and clear all visible state before waiting for
    // the server.  Delayed old reads and media loads can no longer apply.
    session.current += 1;
    refreshSequence.current += 1;
    loginAttempt.current += 1;
    token.current = '';
    clearToken();
    setSigned(false);
    clearUserData(true);
    void player.clear();

    if (oldToken) {
      api('/logout', {}, {token: oldToken, clearOnSuccess: false}).catch(() => {});
    }
  };

  const runCurrent = async work => {
    const generation = session.current;
    const requestToken = token.current;
    if (!requestToken || !signed) return;
    setError('');
    try {
      await work(requestToken, generation);
    } catch (reason) {
      if (isCurrent(generation)) setError(reason && reason.message ? reason.message : 'request_failed');
    }
  };

  const addGoal = () => runCurrent(async (requestToken, generation) => {
    const serial = goalSequence.current++;
    const id = `goal-${Date.now()}-${serial}`;
    await api('/goals', {id, title}, {token: requestToken});
    if (!isCurrent(generation)) return;
    setTitle('');
    await refresh(generation, requestToken);
  });

  const completeGoal = id => runCurrent(async (requestToken, generation) => {
    await api('/complete-goal', {id}, {token: requestToken});
    if (!isCurrent(generation)) return;
    await refresh(generation, requestToken);
  });

  const submitSurvey = () => runCurrent(async (requestToken, generation) => {
    const values = {};
    for (const question of questions) {
      const raw = answers[question.id];
      if (raw !== undefined && String(raw).trim() !== '') values[question.id] = Number(raw);
    }
    await api('/surveys', {answers: values}, {token: requestToken});
    if (!isCurrent(generation)) return;
    setAnswers({});
    await refresh(generation, requestToken);
    if (isCurrent(generation)) setTab('Results');
  });

  const activate = () => runCurrent(async (requestToken, generation) => {
    await api('/activate', {
      transaction_id: transaction,
      product,
      store,
    }, {token: requestToken});
    if (!isCurrent(generation)) return;
    setTransaction('');
    await refresh(generation, requestToken);
  });

  const playTrack = track => runCurrent((requestToken) => player.play(track, origin(), requestToken));
  const pause = () => runCurrent(() => player.pause());
  const resume = () => runCurrent(() => player.resume());

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.page}>
      <Text style={styles.heading}>Practice companion</Text>
      <Text accessibilityRole="alert" testID="error">{error}</Text>
      {!signed ? (
        <View style={styles.card}>
          <Text>Login</Text>
          <TextInput
            testID="login"
            value={login}
            onChangeText={setLogin}
            style={styles.input}
            autoCapitalize="none"
          />
          <Text>Password</Text>
          <TextInput
            testID="password"
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            style={styles.input}
          />
          <Button title="Sign in" testID="signin" disabled={loggingIn} onPress={signIn} />
        </View>
      ) : (
        <>
          <View style={styles.row}>
            <Text>Signed in</Text>
            <Button title="Sign out" testID="logout" onPress={logout} />
          </View>
          <View style={styles.row}>
            {['Audio', 'Goals', 'Survey', 'Results', 'Subscription'].map(name => (
              <Button
                key={name}
                title={name}
                onPress={() => setTab(name)}
                testID={`tab-${name.toLowerCase()}`}
              />
            ))}
          </View>

          {tab === 'Audio' && (
            <View style={styles.card}>
              <Text style={styles.subheading}>Playlists</Text>
              {tracks.map(track => (
                <View key={track.id} style={styles.row}>
                  <Text>{track.title}</Text>
                  <Button
                    title={`Play ${track.title}`}
                    testID={`play-${track.id}`}
                    onPress={() => playTrack(track)}
                  />
                </View>
              ))}
              <Text testID="playback">
                {progress.isPlaying ? 'Playing' : 'Paused'} {progress.position.toFixed(1)}
              </Text>
              <View style={styles.row}>
                <Button title="Pause" testID="pause" onPress={pause} />
                <Button title="Resume" testID="resume" onPress={resume} />
              </View>
            </View>
          )}

          {tab === 'Goals' && (
            <View style={styles.card}>
              <Text style={styles.subheading}>Goals</Text>
              <TextInput
                testID="goal-title"
                value={title}
                onChangeText={setTitle}
                placeholder="Goal title"
                style={styles.input}
              />
              <Button title="Add goal" testID="add-goal" onPress={addGoal} />
              {goals.map(goal => (
                <View key={goal.id} style={styles.row}>
                  <Text>{goal.title}</Text>
                  <Text testID={`goal-status-${goal.id}`}>
                    {goal.complete ? 'Complete' : 'Open'}
                  </Text>
                  {!goal.complete && (
                    <Button
                      title="Complete goal"
                      testID={`complete-${goal.id}`}
                      onPress={() => completeGoal(goal.id)}
                    />
                  )}
                </View>
              ))}
            </View>
          )}

          {tab === 'Survey' && (
            <View style={styles.card}>
              <Text style={styles.subheading}>Current survey</Text>
              {questions.map(question => (
                <View key={question.id}>
                  <Text>{question.label}</Text>
                  <TextInput
                    testID={`answer-${question.id}`}
                    value={answers[question.id] ?? ''}
                    onChangeText={value => setAnswers(previous => ({...previous, [question.id]: value}))}
                    keyboardType="decimal-pad"
                    style={styles.input}
                  />
                </View>
              ))}
              <Button title="Submit survey" testID="submit-survey" onPress={submitSurvey} />
            </View>
          )}

          {tab === 'Results' && (
            <View style={styles.card}>
              <Text style={styles.subheading}>Survey results</Text>
              <Text testID="survey-count">Submissions: {report.count}</Text>
              <View style={styles.row}>
                <Button title="Latest" testID="latest" onPress={() => setMode('latest')} />
                <Button title="Overall" testID="overall" onPress={() => setMode('overall')} />
              </View>
              {report.count === 0 ? (
                <Text testID="no-results">No survey submissions yet.</Text>
              ) : (
                <View style={styles.chart}>
                  {questions.map(question => {
                    const raw = report[mode] && report[mode][question.id];
                    const value = typeof raw === 'number' && Number.isFinite(raw) ? raw : 0;
                    return (
                      <View key={question.id} style={styles.column}>
                        <View
                          testID={`bar-${question.id}`}
                          accessibilityLabel={`${question.label} ${value.toFixed(2)}`}
                          style={[styles.bar, {height: Math.max(0, Math.min(10, value)) * 12}]}
                        />
                        <Text>{question.label}</Text>
                        <Text testID={`score-${question.id}`}>{value.toFixed(2)}</Text>
                      </View>
                    );
                  })}
                </View>
              )}
            </View>
          )}

          {tab === 'Subscription' && (
            <View style={styles.card}>
              <Text style={styles.subheading}>Subscription receipt</Text>
              <Text>Product</Text>
              <TextInput testID="product" value={product} onChangeText={setProduct} style={styles.input} />
              <Text>Store</Text>
              <TextInput testID="store" value={store} onChangeText={setStore} style={styles.input} />
              <Text>Local transaction ID</Text>
              <TextInput testID="transaction" value={transaction} onChangeText={setTransaction} style={styles.input} />
              <Button title="Verify receipt" testID="activate" onPress={activate} />
              {subscriptions.map(subscription => (
                <Text key={subscription.transaction_id}>
                  {subscription.product} ({subscription.store})
                </Text>
              ))}
            </View>
          )}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: {flex: 1, backgroundColor: '#f1f4f2'},
  page: {width: '100%', maxWidth: 1000, alignSelf: 'center', padding: 22, paddingTop: 50, paddingBottom: 50},
  heading: {fontSize: 32, color: '#25483f', fontWeight: '700', marginBottom: 20},
  subheading: {fontSize: 22, fontWeight: '600', marginBottom: 12},
  card: {backgroundColor: 'white', padding: 20, borderRadius: 10, marginVertical: 14},
  row: {flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginVertical: 8},
  button: {backgroundColor: '#dcece5', borderRadius: 6, padding: 12},
  disabledButton: {opacity: 0.5},
  input: {borderColor: '#abc1b8', borderWidth: 1, borderRadius: 5, padding: 10, marginVertical: 10},
  chart: {height: 180, flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-around', marginTop: 24},
  column: {flex: 1, minWidth: 0, alignItems: 'center'},
  bar: {width: '75%', backgroundColor: '#397c64'},
});
