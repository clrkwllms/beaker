import unittest, datetime, os, threading
from time import sleep
from bkr.server.model import TaskStatus, Job, System, User, \
        Group, SystemStatus, SystemActivity, Recipe, LabController
import sqlalchemy.orm
from turbogears.database import session
from bkr.inttest import data_setup, stub_cobbler
from bkr.inttest.assertions import assert_datetime_within, \
        assert_durations_not_overlapping
from bkr.server.tools import beakerd

class TestBeakerd(unittest.TestCase):

    def setUp(self):
        self.stub_cobbler_thread = stub_cobbler.StubCobblerThread()
        self.stub_cobbler_thread.start()
        with session.begin():
            self.lab_controller = data_setup.create_labcontroller(
                    fqdn=u'localhost:%d' % self.stub_cobbler_thread.port)
            data_setup.create_system(lab_controller=self.lab_controller,
                    shared=True)

    def tearDown(self):
        self.stub_cobbler_thread.stop()

    def _check_job_status(self, jobs, status):
        with session.begin():
            for j in jobs:
                job = Job.by_id(j.id)
                self.assertEqual(job.status,TaskStatus.by_name(status))
        session.close()

    def _create_cached_status(self):
        TaskStatus.by_name(u'Processed')
        TaskStatus.by_name(u'Queued')

    def test_cache_new_to_queued(self):
        from nose.plugins.skip import SkipTest
        raise SkipTest('FIXME')

        self._create_cached_status()
        with session.begin():
            jobs = list()
            distro = data_setup.create_distro()
            for i in range(2):
                job = data_setup.create_job(whiteboard=u'job_%s' % i, distro=distro)
                jobs.append(job)

        #We need to run our beakerd methods as threads to ensure
        #that we have seperate sessions that create/read our cached object
        class Do(threading.Thread):
            def __init__(self,target,*args,**kw):
                super(Do,self).__init__(*args,**kw)
                self.target = target
            def run(self, *args, **kw):
                self.success = self.target()

        thread_new_recipe = Do(target=beakerd.new_recipes)

        thread_new_recipe.start()
        thread_new_recipe.join()
        self.assertTrue(thread_new_recipe.success)
        self._check_job_status(jobs, u'Processed')

        thread_processed_recipe = Do(target=beakerd.processed_recipesets)
        thread_processed_recipe.start()
        thread_processed_recipe.join()
        self.assertTrue(thread_processed_recipe.success)
        self._check_job_status(jobs, u'Queued')

    def test_loaned_machine_can_be_scheduled(self):
        with session.begin():
            user = data_setup.create_user()
            distro = data_setup.create_distro()
            system = data_setup.create_system(status=u'Automated', shared=True,
                    lab_controller=self.lab_controller)
            # System has groups, which the user is not a member of, but is loaned to the user
            system.loaned = user
            data_setup.add_group_to_system(system, data_setup.create_group())
            job = data_setup.create_job(owner=user, distro=distro)
            job.recipesets[0].recipes[0]._host_requires = (
                    '<hostRequires><hostname op="=" value="%s"/></hostRequires>'
                    % system.fqdn)
        beakerd.new_recipes()
        with session.begin():
            job = Job.query.get(job.id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Processed'))

    def test_reservations_are_created(self):
        with session.begin():
            data_setup.create_task(name=u'/distribution/install')
            user = data_setup.create_user()
            distro = data_setup.create_distro()
            system = data_setup.create_system(owner=user, status=u'Automated',
                    shared=True, lab_controller=self.lab_controller)
            job = data_setup.create_job(owner=user, distro=distro)
            job.recipesets[0].recipes[0]._host_requires = (
                    '<hostRequires><and><hostname op="=" value="%s"/></and></hostRequires>'
                    % system.fqdn)

        beakerd.new_recipes()
        beakerd.processed_recipesets()
        beakerd.queued_recipes()

        with session.begin():
            job = Job.query.get(job.id)
            system = System.query.get(system.id)
            user = User.query.get(user.user_id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Scheduled'))
            self.assertEqual(system.reservations[0].type, u'recipe')
            self.assertEqual(system.reservations[0].user, user)
            assert_datetime_within(system.reservations[0].start_time,
                    tolerance=datetime.timedelta(seconds=60),
                    reference=datetime.datetime.utcnow())
            self.assert_(system.reservations[0].finish_time is None)
            assert_durations_not_overlapping(system.reservations)

    def test_empty_and_element(self):
        with session.begin():
            data_setup.create_task(name=u'/distribution/install')
            user = data_setup.create_user()
            distro = data_setup.create_distro()
            job = data_setup.create_job(owner=user, distro=distro)
            job.recipesets[0].recipes[0]._host_requires = (
                    u'<hostRequires><and></and></hostRequires>')

        beakerd.new_recipes()

        with session.begin():
            job = Job.query.get(job.id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Processed'))

    def test_or_lab_controller(self):
        with session.begin():
            data_setup.create_task(name=u'/distribution/install')
            user = data_setup.create_user()
            lc1 = data_setup.create_labcontroller(u'lab1')
            lc2 = data_setup.create_labcontroller(u'lab2')
            lc3 = data_setup.create_labcontroller(u'lab3')
            distro = data_setup.create_distro()
            system1 = data_setup.create_system(arch=u'i386', shared=True)
            system1.lab_controller = lc1
            system2 = data_setup.create_system(arch=u'i386', shared=True)
            system2.lab_controller = lc2
            system3 = data_setup.create_system(arch=u'i386', shared=True)
            system3.lab_controller = lc3
            job = data_setup.create_job(owner=user, distro=distro)
            job.recipesets[0].recipes[0]._host_requires = (u"""
                   <hostRequires>
                    <or>
                     <hostlabcontroller op="=" value="lab1"/>
                     <hostlabcontroller op="=" value="lab2"/>
                    </or>
                   </hostRequires>
                   """)

        beakerd.new_recipes()

        with session.begin():
            job = Job.query.get(job.id)
            system1 = System.query.get(system1.id)
            system2 = System.query.get(system2.id)
            system3 = System.query.get(system3.id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Processed'))
            candidate_systems = job.recipesets[0].recipes[0].systems
            self.assertEqual(len(candidate_systems), 2)
            self.assert_(system1 in candidate_systems)
            self.assert_(system2 in candidate_systems)
            self.assert_(system3 not in candidate_systems)

    def check_user_cannot_run_job_on_system(self, user, system):
        """
        Asserts that the given user is not allowed to run a job against the 
        given system, i.e. that it aborts due to no matching systems.
        """
        with session.begin():
            distro = data_setup.create_distro()
            job = data_setup.create_job(owner=user, distro=distro)
            job.recipesets[0].recipes[0]._host_requires = (
                    '<hostRequires><hostname op="=" value="%s"/></hostRequires>'
                    % system.fqdn)
        beakerd.new_recipes()
        with session.begin():
            job = Job.query.get(job.id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Aborted'))
        return job.id

    def check_user_can_run_job_on_system(self, user, system):
        """
        Asserts that the given user *is* allowed to run a job against the given 
        system, i.e. that it does not abort due to no matching systems. Inverse 
        of the method above.
        """
        with session.begin():
            distro = data_setup.create_distro()
            job = data_setup.create_job(owner=user, distro=distro)
            job.recipesets[0].recipes[0]._host_requires = (
                    '<hostRequires><hostname op="=" value="%s"/></hostRequires>'
                    % system.fqdn)
        beakerd.new_recipes()
        with session.begin():
            job = Job.query.get(job.id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Processed'))
        return job.id

    def test_nonshared_system_not_owner(self):
        with session.begin():
            user = data_setup.create_user()
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    shared=False, owner=data_setup.create_user())
        self.check_user_cannot_run_job_on_system(user, system)

    def test_nonshared_system_owner(self):
        with session.begin():
            user = data_setup.create_user()
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    shared=False, owner=user)
        self.check_user_can_run_job_on_system(user, system)

    def test_nonshared_system_admin(self):
        with session.begin():
            admin = data_setup.create_admin()
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    shared=False)
        self.check_user_cannot_run_job_on_system(admin, system)

    def test_shared_system_not_owner(self):
        with session.begin():
            user = data_setup.create_user()
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    shared=True)
        self.check_user_can_run_job_on_system(user, system)

    def test_shared_system_admin(self):
        with session.begin():
            admin = data_setup.create_admin()
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    shared=True)
        self.check_user_can_run_job_on_system(admin, system)

    def test_shared_group_system_with_user_not_in_group(self):
        with session.begin():
            user = data_setup.create_user()
            group = data_setup.create_group()
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    shared=True)
            system.groups.append(group)
        self.check_user_cannot_run_job_on_system(user, system)

    def test_shared_group_system_with_user_in_group(self):
        with session.begin():
            group = data_setup.create_group()
            user = data_setup.create_user()
            user.groups.append(group)
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    shared=True)
            system.groups.append(group)
        self.check_user_can_run_job_on_system(user, system)

    def test_shared_group_system_with_admin_not_in_group(self):
        with session.begin():
            admin = data_setup.create_admin()
            group = data_setup.create_group()
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    shared=True)
            system.groups.append(group)
        self.check_user_cannot_run_job_on_system(admin, system)

    def test_shared_group_system_with_admin_in_group(self):
        with session.begin():
            group = data_setup.create_group()
            admin = data_setup.create_admin()
            admin.groups.append(group)
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    shared=True)
            system.groups.append(group)
        self.check_user_can_run_job_on_system(admin, system)

    def test_loaned_system_with_admin(self):
        with session.begin():
            loanee = data_setup.create_user()
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    loaned=loanee)
            admin = data_setup.create_admin()
        self.check_user_cannot_run_job_on_system(admin, system)

    def test_loaned_system_with_loanee(self):
        with session.begin():
            loanee = data_setup.create_user()
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    loaned=loanee)
        job_id = self.check_user_can_run_job_on_system(loanee, system)
        beakerd.processed_recipesets()
        with session.begin():
            job = Job.query.get(job_id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Queued'))
        beakerd.queued_recipes()
        with session.begin():
            job = Job.query.get(job_id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Scheduled'))
            system = System.query.get(system.id)
            self.assertEqual(system.user.user_id, loanee.user_id)

    def test_loaned_system_with_not_loanee(self):
        with session.begin():
            loanee = data_setup.create_user()
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    loaned=loanee)
            user = data_setup.create_user()
        self.check_user_cannot_run_job_on_system(user, system)

    def test_loaned_system_with_owner(self):
        with session.begin():
            loanee = data_setup.create_user()
            owner = data_setup.create_user()
            system = data_setup.create_system(lab_controller=self.lab_controller,
                    owner=owner, loaned=loanee)
        # owner of the system has access, when the
        # loan is returned their job will be able to run.
        job_id = self.check_user_can_run_job_on_system(owner, system)
        beakerd.processed_recipesets()
        with session.begin():
            job = Job.query.get(job_id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Queued'))
        # Even though the system is free the job should stay queued while
        # the loan is in place.
        beakerd.queued_recipes()
        with session.begin():
            job = Job.query.get(job_id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Queued'))
            system = System.query.get(system.id)
            self.assertEqual(system.user, None)
    
    def test_fail_harness_repo(self):
        with session.begin():
            data_setup.create_task(name=u'/distribution/install')
            user = data_setup.create_user()
            distro = data_setup.create_distro()
            system = data_setup.create_system(owner=user, status=u'Automated', shared=True,
                    lab_controller=self.lab_controller)
            job = data_setup.create_job(owner=user, distro=distro)
            recipe = job.recipesets[0].recipes[0]
            recipe._host_requires = (
                    u'<hostRequires><and><hostname op="=" value="%s"/></and></hostRequires>'
                    % system.fqdn)

        harness_dir = '%s/%s' % (recipe.harnesspath, \
            recipe.distro.osversion.osmajor)
        try:
            if os.path.exists(harness_dir):
                os.rmdir(harness_dir)
            beakerd.new_recipes()
            beakerd.processed_recipesets()
            beakerd.queued_recipes()

            with session.begin():
                for r in Recipe.query:
                    if r.system:
                        r.system.lab_controller = self.lab_controller
            beakerd.scheduled_recipes()
            with session.begin():
                job = Job.by_id(job.id)
                self.assertEqual(job.status, TaskStatus.by_name(u'Aborted'))
        finally:
            if not os.path.exists(harness_dir):
                os.mkdir(harness_dir)
    
    def test_success_harness_repo(self):
        with session.begin():
            data_setup.create_task(name=u'/distribution/install')
            user = data_setup.create_user()
            distro = data_setup.create_distro()
            system = data_setup.create_system(owner=user, status=u'Automated',
                    shared=True, lab_controller=self.lab_controller)
            job = data_setup.create_job(owner=user, distro=distro)
            recipe = job.recipesets[0].recipes[0]
            recipe._host_requires = (
                    '<hostRequires><and><hostname op="=" value="%s"/></and></hostRequires>'
                    % system.fqdn)

        harness_dir = '%s/%s' % (recipe.harnesspath, \
            recipe.distro.osversion.osmajor)

        if not os.path.exists(harness_dir):
            os.mkdir(harness_dir)
        beakerd.new_recipes()
        beakerd.processed_recipesets()
        beakerd.queued_recipes()
        with session.begin():
            for r in Recipe.query:
                if r.system:
                    r.system.lab_controller = self.lab_controller
        beakerd.scheduled_recipes()
        with session.begin():
            job = Job.by_id(job.id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Running'))

    def test_successful_recipe_start(self):
        with session.begin():
            distro = data_setup.create_distro()
            system = data_setup.create_system(shared=True,
                    lab_controller=self.lab_controller)
            job = data_setup.create_job(distro=distro)
            job.recipesets[0].recipes[0]._host_requires = (u"""
                <hostRequires>
                    <hostname op="=" value="%s" />
                </hostRequires>
                """ % system.fqdn)

        beakerd.new_recipes()
        beakerd.processed_recipesets()
        beakerd.queued_recipes()
        beakerd.scheduled_recipes()
        beakerd.queued_commands()

        with session.begin():
            job = Job.query.get(job.id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Running'))
            self.assertEqual(self.stub_cobbler_thread.cobbler\
                    .system_actions[system.fqdn], 'reboot')

class TestPowerFailures(unittest.TestCase):

    def setUp(self):
        self.stub_cobbler_thread = stub_cobbler.StubCobblerThread()
        self.stub_cobbler_thread.start()
        with session.begin():
            self.lab_controller = data_setup.create_labcontroller(
                    fqdn=u'localhost:%d' % self.stub_cobbler_thread.port)

    def tearDown(self):
        self.stub_cobbler_thread.stop()

    # https://bugzilla.redhat.com/show_bug.cgi?id=738423
    def test_unreserve(self):
        with session.begin():
            user = data_setup.create_user()
            automated_system = data_setup.create_system(fqdn=u'raise1.example.org',
                                                        lab_controller=self.lab_controller,owner = user,
                                                        status = SystemStatus.by_name(u'Automated'))
            automated_system.reserve(u'Scheduler', user)
            session.flush()
            automated_system.unreserve(u'Scheduler', user)
        beakerd.queued_commands()
        beakerd.running_commands()
        with session.begin():
            automated_system = System.query.get(automated_system.id)
            system_activity = automated_system.dyn_activity\
                    .filter(SystemActivity.field_name == u'Power').first()
            self.assertEqual(system_activity.action, 'off')
            self.assertTrue(system_activity.new_value.startswith('Failed'))

    def test_automated_system_marked_broken(self):
        with session.begin():
            automated_system = data_setup.create_system(fqdn=u'broken1.example.org',
                                                        lab_controller=self.lab_controller,
                                                        status = SystemStatus.by_name(u'Automated'))
            automated_system.action_power(u'on')
        beakerd.queued_commands()
        beakerd.running_commands()
        with session.begin():
            automated_system = System.query.get(automated_system.id)
            self.assertEqual(automated_system.status, SystemStatus.by_name(u'Broken'))
            system_activity = automated_system.activity[0]
            self.assertEqual(system_activity.action, 'on')
            self.assertTrue(system_activity.new_value.startswith('Failed'))

    # https://bugzilla.redhat.com/show_bug.cgi?id=720672
    def test_manual_system_status_not_changed(self):
        with session.begin():
            manual_system = data_setup.create_system(fqdn = u'broken2.example.org',
                                                     lab_controller = self.lab_controller,
                                                     status = SystemStatus.by_name(u'Manual'))
            manual_system.action_power(u'on')
        beakerd.queued_commands()
        beakerd.running_commands()
        with session.begin():
            manual_system = System.query.get(manual_system.id)
            self.assertEqual(manual_system.status, SystemStatus.by_name(u'Manual'))
            system_activity = manual_system.activity[0]
            self.assertEqual(system_activity.action, 'on')
            self.assertTrue(system_activity.new_value.startswith('Failed'))

    def test_mark_broken_updates_history(self):
        with session.begin():
            system = data_setup.create_system(status = SystemStatus.by_name(u'Automated'))
            system.mark_broken(reason = "Attacked by cyborgs")
        with session.begin():
            system = System.query.get(system.id)
            system_activity = system.dyn_activity.filter(SystemActivity.field_name == u'Status').first()
            self.assertEqual(system_activity.old_value, u'Automated')
            self.assertEqual(system_activity.new_value, u'Broken')

    def test_broken_power_aborts_recipe(self):
        with session.begin():
            system = data_setup.create_system(fqdn = u'broken.dreams.example.org',
                                              lab_controller = self.lab_controller,
                                              status = SystemStatus.by_name(u'Automated'),
                                              shared = True)
            distro = data_setup.create_distro()
            job = data_setup.create_job(distro=distro)
            job.recipesets[0].recipes[0]._host_requires = (u"""
                <hostRequires>
                    <hostname op="=" value="%s" />
                </hostRequires>
                """ % system.fqdn)

        beakerd.new_recipes()
        beakerd.processed_recipesets()
        beakerd.queued_recipes()
        beakerd.scheduled_recipes()
        beakerd.queued_commands()

        with session.begin():
            job = Job.query.get(job.id)
            self.assertEqual(job.status, TaskStatus.by_name(u'Running'))

        beakerd.running_commands()
        with session.begin():
            job = Job.query.get(job.id)
            self.assertEqual(job.recipesets[0].recipes[0].status,
                             TaskStatus.by_name(u'Aborted'))
