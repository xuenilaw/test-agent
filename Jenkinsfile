pipeline {
    agent {
        docker {
            // Match the playwright package in uv.lock, including the patch version.
            image 'mcr.microsoft.com/playwright/python:v1.63.0-noble'
            args '--user 0:0 --ipc=host'
        }
    }
    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }
    triggers { pollSCM('H/5 * * * *') }
    environment {
        VISION_PROVIDER = 'clef'
        VISION_MODEL = 'cloudflare/clef'
        PLAYWRIGHT_BROWSERS_PATH = '/ms-playwright'
        UV_PROJECT_ENVIRONMENT = '/tmp/wbs-ci-venv'
        UV_CACHE_DIR = '/tmp/wbs-uv-cache'
        UV_PYTHON_DOWNLOADS = 'never'
    }
    stages {
        stage('Setup') {
            steps {
                // Prevent stale plans/artifacts/.env from earlier workspace builds.
                deleteDir()
                checkout scm
                sh '''
                    test ! -f .env
                    python -m pip install --disable-pip-version-check uv==0.12.17
                    uv sync --locked
                '''
            }
        }
        stage('Unit tests') {
            steps { sh 'uv run python -m unittest discover -s tests -v' }
        }
        stage('Test suite') {
            steps {
                withCredentials([
                    string(credentialsId: 'wbs-openai-api-key', variable: 'OPENAI_API_KEY'),
                    string(credentialsId: 'wbs-openai-base-url', variable: 'OPENAI_BASE_URL'),
                    string(credentialsId: 'wbs-openai-model', variable: 'OPENAI_MODEL'),
                    string(credentialsId: 'wbs-openrouter-api-key', variable: 'OPENROUTER_API_KEY'),
                    string(credentialsId: 'wbs-anthropic-api-key', variable: 'ANTHROPIC_API_KEY')
                ]) {
                    script {
                        def code = sh(returnStatus: true, script: '''
                            set +x
                            uv run python -m test_agent suite cases/osm/WBS_testcase1_osm.xlsx --locators cases/osm/locators.json
                        ''')
                        def result = sh(returnStdout: true,
                            script: "python ci/suite_result.py ${code}").trim()
                        if (result == 'UNSTABLE') {
                            unstable('Suite finished with FAILED/BLOCKED test cases. Inspect the archived report and audit.csv.')
                        } else if (result != 'SUCCESS') {
                            error("Suite infrastructure error or incomplete evidence (exit ${code}).")
                        }
                    }
                }
            }
        }
    }
    post {
        always {
            archiveArtifacts artifacts: 'artifacts/suite-*/**', allowEmptyArchive: true
        }
    }
}
