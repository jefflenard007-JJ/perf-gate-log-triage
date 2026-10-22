// Jenkins equivalent of .gitlab-ci.yml, for teams running Jenkins.
// Needs JMeter and Python 3 on the agent.
pipeline {
  agent any
  parameters {
    string(name: 'TARGET_HOST', defaultValue: 'localhost', description: 'Host of the service under test')
    string(name: 'TARGET_PORT', defaultValue: '8000')
    string(name: 'USERS', defaultValue: '20')
    string(name: 'DURATION', defaultValue: '120', description: 'Seconds')
  }
  stages {
    stage('Unit tests') {
      steps {
        sh 'python3 -m pip install -e ".[dev]"'
        sh 'python3 -m pytest -q --junitxml=report.xml'
      }
      post { always { junit 'report.xml' } }
    }
    stage('JMeter load test') {
      steps {
        sh '''
          mkdir -p results
          jmeter -n -t loadtests/jmeter/orders-load.jmx \
            -JHOST=${TARGET_HOST} -JPORT=${TARGET_PORT} -JUSERS=${USERS} -JDURATION=${DURATION} \
            -Jjmeter.save.saveservice.output_format=csv \
            -l results/results.jtl -e -o results/html
        '''
      }
    }
    stage('Performance gate') {
      steps {
        sh '''
          python3 -m perfgate.cli check results/results.jtl \
            --baseline baselines/orders-api.json --config perfgate.config.json \
            --report results/perf-report.md --db perf-history.db
        '''
      }
    }
  }
  post {
    always {
      archiveArtifacts artifacts: 'results/**, perf-history.db', allowEmptyArchive: true
    }
  }
}
